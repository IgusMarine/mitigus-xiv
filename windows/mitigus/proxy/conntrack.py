"""
Tabela de rastreio de conexão (o equivalente Windows do SO_ORIGINAL_DST).

O Windows não tem SO_ORIGINAL_DST/TPROXY: quando desviamos o pacote do PS5 para
o proxy local, o destino ORIGINAL (o servidor do FFXIV) se perde. Então quando
vemos o SYN do PS5 (no loop WinDivert) gravamos aqui o mapeamento
(ip/porta do PS5) -> (ip/porta do servidor). O relay, ao aceitar a conexão,
descobre o peer (o PS5) e consulta esta tabela para saber com quem realmente
conectar upstream.

Thread-safe: o loop de pacotes (thread do WinDivert) escreve; o relay (loop
asyncio, outra thread) lê.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Optional, Tuple

Endpoint = Tuple[str, int]
_Key = Tuple[str, int]


class ConnTrack:
    def __init__(self, ttl: float = 120.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._map: Dict[_Key, list] = {}  # key -> [Endpoint, last_seen]
        self._lock = threading.Lock()
        self._ttl = ttl
        self._clock = clock

    def remember(self, src_ip: str, src_port: int, dst_ip: str, dst_port: int) -> None:
        with self._lock:
            self._map[(src_ip, src_port)] = [(dst_ip, dst_port), self._clock()]

    def lookup(self, src_ip: str, src_port: int) -> Optional[Endpoint]:
        with self._lock:
            entry = self._map.get((src_ip, src_port))
            if entry is None:
                return None
            entry[1] = self._clock()  # mantém vivo enquanto há tráfego
            return entry[0]

    def forget(self, src_ip: str, src_port: int) -> None:
        with self._lock:
            self._map.pop((src_ip, src_port), None)

    def gc(self) -> int:
        """Remove entradas paradas há mais de ttl. Devolve quantas removeu."""
        now = self._clock()
        with self._lock:
            dead = [k for k, (_, ts) in self._map.items() if now - ts > self._ttl]
            for k in dead:
                del self._map[k]
            return len(dead)

    def __len__(self) -> int:
        with self._lock:
            return len(self._map)
