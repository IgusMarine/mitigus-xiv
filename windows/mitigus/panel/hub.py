"""
Hub de controle e telemetria (Fase 5).

Estado compartilhado, thread-safe, entre o proxy (loop asyncio) e o painel web
(servidor HTTP em thread separada): o flag liga/desliga da mitigação e a
telemetria do corte de lock ao vivo. O Mitigator reporta aqui; o painel lê daqui.
"""
from __future__ import annotations

import collections
import threading
import time
from typing import Callable, Optional


class ControlHub:
    # limites da margem de segurança (segundos)
    EXTRA_DELAY_MIN = 0.06
    EXTRA_DELAY_MAX = 0.15

    def __init__(
        self,
        enabled: bool = True,
        extra_delay: float = 0.075,
        log_size: int = 200,
        clock: Callable[[], float] = time.time,
    ):
        self._lock = threading.Lock()
        self._enabled = enabled
        self._clock = clock
        self._logs: collections.deque = collections.deque(maxlen=log_size)
        self._tele = self._blank()
        self._started_at = clock()
        self._flows = 0
        self._config = {"extra_delay": float(extra_delay), "qos": False}
        self._info: dict = {}
        # janela do ping SENTIDO (rtt por ação) p/ jitter + percentis no painel
        self._rtt_samples: collections.deque = collections.deque(maxlen=120)
        self._jitter_ms = 0.0          # EMA /16 (RFC3550)
        self._prev_rtt_ms: Optional[float] = None
        # ping de REDE (perna PC->servidor), vindo do SIO_TCP_INFO
        self._net = {"wan_ms": None, "wan_min_ms": None, "retrans": None, "updated_at": None}
        # rota opcional (VPS via SOCKS5) — off por padrão; só o upstream do jogo
        self._route = {"mode": "off", "host": "", "port": 1080}

    @staticmethod
    def _blank() -> dict:
        return {
            "last_rtt_ms": None,
            "last_original_ms": None,
            "last_reduced_ms": None,
            "last_saved_ms": None,
            "total_actions": 0,
            "total_saved_ms": 0,
            "updated_at": None,
        }

    # ---- liga/desliga ----------------------------------------------------
    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_enabled(self, value: bool) -> bool:
        with self._lock:
            self._enabled = bool(value)
            self._log_locked(f"mitigação {'LIGADA' if self._enabled else 'DESLIGADA'}")
            return self._enabled

    def toggle(self) -> bool:
        with self._lock:
            self._enabled = not self._enabled
            self._log_locked(f"mitigação {'LIGADA' if self._enabled else 'DESLIGADA'}")
            return self._enabled

    # ---- telemetria ------------------------------------------------------
    def record_effect(self, original_ms: float, reduced_ms: float, rtt_ms: Optional[float]) -> None:
        with self._lock:
            original = int(original_ms)
            reduced = int(reduced_ms)
            saved = max(0, original - reduced)
            self._tele["last_rtt_ms"] = None if rtt_ms is None else int(rtt_ms)
            self._tele["last_original_ms"] = original
            self._tele["last_reduced_ms"] = reduced
            self._tele["last_saved_ms"] = saved
            self._tele["total_actions"] += 1
            self._tele["total_saved_ms"] += saved
            self._tele["updated_at"] = self._clock()
            if rtt_ms is not None:
                r = float(rtt_ms)
                self._rtt_samples.append(r)
                if self._prev_rtt_ms is not None:  # jitter EMA /16 (RFC3550 A.8)
                    self._jitter_ms += (abs(r - self._prev_rtt_ms) - self._jitter_ms) / 16.0
                self._prev_rtt_ms = r

    def record_net(self, wan_ms: Optional[float], wan_min_ms: Optional[float] = None,
                   retrans: Optional[int] = None) -> None:
        """Ping de rede da perna PC->servidor (SIO_TCP_INFO). Sem extra de tráfego."""
        with self._lock:
            self._net["wan_ms"] = None if wan_ms is None else round(float(wan_ms), 1)
            self._net["wan_min_ms"] = None if wan_min_ms is None else round(float(wan_min_ms), 1)
            self._net["retrans"] = None if retrans is None else int(retrans)
            self._net["updated_at"] = self._clock()

    @staticmethod
    def _pct(samples: list, p: float) -> Optional[float]:
        if not samples:
            return None
        s = sorted(samples)
        k = (len(s) - 1) * p
        lo = int(k)
        hi = min(lo + 1, len(s) - 1)
        return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)

    def note_flow(self) -> None:
        with self._lock:
            self._flows += 1

    # ---- configuração (ajustável pela UI) --------------------------------
    def extra_delay(self) -> float:
        with self._lock:
            return self._config["extra_delay"]

    def get_config(self) -> dict:
        with self._lock:
            return dict(self._config)

    def set_config(self, extra_delay: Optional[float] = None,
                   qos: Optional[bool] = None) -> dict:
        with self._lock:
            if extra_delay is not None:
                ed = max(self.EXTRA_DELAY_MIN, min(self.EXTRA_DELAY_MAX, float(extra_delay)))
                self._config["extra_delay"] = ed
                self._log_locked(f"margem de segurança = {int(ed * 1000)}ms")
            if qos is not None:
                self._config["qos"] = bool(qos)
                self._log_locked(f"QoS anti-bufferbloat {'LIGADO' if qos else 'desligado'}")
            return dict(self._config)

    # ---- rota opcional (VPS) ---------------------------------------------
    def route(self) -> dict:
        with self._lock:
            return dict(self._route)

    def set_route(self, mode=None, host=None, port=None) -> dict:
        with self._lock:
            if mode is not None:
                self._route["mode"] = "socks5" if mode == "socks5" else "off"
            if host is not None:
                self._route["host"] = str(host).strip()
            if port is not None:
                try:
                    self._route["port"] = int(port)
                except (TypeError, ValueError):
                    pass
            self._log_locked(
                f"rota = {self._route['mode']}"
                + (f" ({self._route['host']}:{self._route['port']})" if self._route["mode"] != "off" else ""))
            return dict(self._route)

    def set_info(self, **kwargs) -> None:
        with self._lock:
            self._info.update(kwargs)

    def add_log(self, line: str) -> None:
        with self._lock:
            self._log_locked(line)

    def _log_locked(self, line: str) -> None:
        self._logs.append(f"{time.strftime('%H:%M:%S')}  {line}")

    def logs(self, n: int = 100) -> list:
        with self._lock:
            data = list(self._logs)
        return data[-n:]

    def status(self) -> dict:
        with self._lock:
            tele = dict(self._tele)
            age = (self._clock() - tele["updated_at"]) if tele["updated_at"] else None
            samples = list(self._rtt_samples)
            net = dict(self._net)
            net_age = (self._clock() - net["updated_at"]) if net["updated_at"] else None
            ping = {
                "felt_p50_ms": self._pct(samples, 0.50),   # ping SENTIDO (mediana)
                "felt_p95_ms": self._pct(samples, 0.95),   # cauda ruim
                "jitter_ms": round(self._jitter_ms, 1) if samples else None,
                "wan_ms": net["wan_ms"],                    # perna PC->servidor (rede)
                "wan_min_ms": net["wan_min_ms"],            # piso da rota
                "retrans": net["retrans"],
                "net_age_s": None if net_age is None else int(net_age),
                "samples": samples[-60:],                   # p/ o sparkline
            }
            return {
                "enabled": self._enabled,
                "flows": self._flows,
                "uptime_s": int(self._clock() - self._started_at),
                "telemetry": tele,
                "telemetry_age_s": None if age is None else int(age),
                "config": {"extra_delay_ms": int(round(self._config["extra_delay"] * 1000)),
                           "qos": bool(self._config["qos"])},
                "ping": ping,
                "route": dict(self._route),
                "info": dict(self._info),
            }
