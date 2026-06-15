"""
Controlador anti-bufferbloat dirigido pelo RTT (AQM em user-mode).

O problema: o PS5 começa um download/upload (update, clipe pra PSN), enche o buffer
de subida do PC->provedor, e o ping do JOGO dispara (de 350ms pra 1200ms). Nenhum
roteador doméstico resolve isso pro FFXIV porque não vê o RTT do jogo. Nós vemos
(medimos o RTT da perna PC->servidor a cada 1s pelo SIO_TCP_INFO).

A ideia (estilo CoDel/RED): mantemos uma BASELINE do RTT "bom". Quando o RTT atual
passa da baseline + alvo, derrubamos uma fração crescente do tráfego de FUNDO (não-
jogo, e só pacotes GRANDES = transferência em massa). O TCP do fundo recua, o buffer
esvazia, o ping do jogo volta. O jogo NUNCA é tocado (vai por outro caminho, o proxy).

Off por padrão (derruba pacotes -> opt-in). `update_rtt` é alimentado pelo poller;
`should_drop(payload_len)` decide por pacote no loop do masquerade.
"""
from __future__ import annotations

import random
from typing import Callable, Optional


class BufferbloatController:
    def __init__(self, target_excess_ms: float = 30.0, max_drop: float = 0.4,
                 big_packet_bytes: int = 1000, recent_alpha: float = 0.3,
                 baseline_rise: float = 0.01, rng: Callable[[], float] = random.random):
        self.target_excess_ms = target_excess_ms
        self.max_drop = max_drop
        self.big_packet_bytes = big_packet_bytes
        self._recent_alpha = recent_alpha
        self._baseline_rise = baseline_rise
        self._rng = rng
        self._enabled = False
        self._baseline: Optional[float] = None  # RTT "bom" (piso que sobe devagar)
        self._recent: Optional[float] = None     # EWMA rápida do RTT

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def update_rtt(self, rtt_ms: Optional[float]) -> None:
        if rtt_ms is None or rtt_ms <= 0:
            return
        if self._baseline is None or rtt_ms < self._baseline:
            self._baseline = rtt_ms                      # desce na hora (novo piso)
        else:
            self._baseline += (rtt_ms - self._baseline) * self._baseline_rise  # sobe devagar
        if self._recent is None:
            self._recent = rtt_ms
        else:
            self._recent += (rtt_ms - self._recent) * self._recent_alpha

    def drop_probability(self) -> float:
        if not self._enabled or self._baseline is None or self._recent is None:
            return 0.0
        excess = self._recent - self._baseline
        if excess <= self.target_excess_ms:
            return 0.0
        # rampa linear: 0 no alvo, max_drop em 3x o alvo
        p = (excess - self.target_excess_ms) / (self.target_excess_ms * 2.0)
        return min(self.max_drop, max(0.0, p))

    def should_drop(self, payload_len: int) -> bool:
        """True = derruba este pacote (só pacotes GRANDES, e só sob bufferbloat)."""
        if not self._enabled or payload_len < self.big_packet_bytes:
            return False
        p = self.drop_probability()
        return p > 0.0 and self._rng() < p
