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

from ..net.ports import port_in_ranges


class NatTable:
    """Conntrack + alocação de porta (PAT) do masquerade — NAT CONE.

    Mapeamento INDEPENDENTE do destino: o MESMO socket do aparelho (ip:porta) recebe
    SEMPRE a MESMA porta externa, não importa pra qual servidor ele fale. Isso dá NAT
    Tipo 2 (jogos online conectam: o servidor/peer sempre acha o console na mesma
    porta). A versão antiga era SIMÉTRICA (uma porta por destino) = NAT Tipo 3, que
    quebrava jogos (STUN/peer recebia uma porta e o tráfego saía por outra). Full
    cone: o retorno é aceito de QUALQUER origem pra (proto, porta alocada).
    Thread-safe e testável."""

    def __init__(self, pool: Tuple[int, int] = (20000, 29999), ttl: float = 120.0,
                 clock: Callable[[], float] = time.monotonic):
        self._lo, self._hi = pool
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._fwd = {}   # (proto, dev_ip, dev_port) -> [alloc, last_seen]
        self._rev = {}   # (proto, alloc)            -> (dev_ip, dev_port)
        self._cursor = self._lo

    def _alloc_port(self, proto: str) -> Optional[int]:
        n = self._hi - self._lo + 1
        for _ in range(n):
            p = self._cursor
            self._cursor = self._lo if self._cursor >= self._hi else self._cursor + 1
            if (proto, p) not in self._rev:
                return p
        return None

    def snat(self, proto, dev_ip, dev_port, dst_ip=None, dst_port=None) -> Optional[int]:
        # dst_* são IGNORADOS de propósito (mapeamento independente do destino = cone).
        key = (proto, dev_ip, dev_port)
        with self._lock:
            e = self._fwd.get(key)
            if e is not None:
                e[1] = self._clock()
                return e[0]
            alloc = self._alloc_port(proto)
            if alloc is None:
                return None
            self._fwd[key] = [alloc, self._clock()]
            self._rev[(proto, alloc)] = (dev_ip, dev_port)
            return alloc

    def dnat(self, proto, alloc, internet_ip=None, internet_port=None) -> Optional[Tuple[str, int]]:
        # full cone: aceita o retorno de QUALQUER origem pra (proto, porta alocada).
        with self._lock:
            dev = self._rev.get((proto, alloc))
            if dev is None:
                return None
            e = self._fwd.get((proto, dev[0], dev[1]))
            if e is not None:
                e[1] = self._clock()
            return dev

    def gc(self) -> int:
        now = self._clock()
        with self._lock:
            dead = [k for k, e in self._fwd.items() if now - e[1] > self._ttl]
            for key in dead:
                alloc = self._fwd.pop(key)[0]
                self._rev.pop((key[0], alloc), None)
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
            # [diag] o masquerade NÃO deveria ver pacote de jogo (o DivertNat pega antes).
            # Se isto logar, o NAT geral está "roubando" o tráfego do FFXIV.
            if packet.tcp is not None and port_in_ranges(packet.dst_port):
                self._log(f"[diag] MASQ pegou porta-jogo {packet.src_addr}:{packet.src_port}"
                          f" -> {packet.dst_addr}:{packet.dst_port}")
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
        while not self._stop.wait(15.0):
            freed = self.nat.gc()
            if freed:
                self._log(f"gc: {freed} fluxo(s) expirado(s)")
            # [diag] enviados x retornos casados x fluxos vivos. Se 'retornos' fica ~0
            # enquanto 'enviados' sobe, as respostas não estão voltando pro aparelho.
            self._log(f"[diag] stats: enviados={self.out_packets} "
                      f"retornos={self.in_matched} fluxos_vivos={len(self.nat)}")

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
