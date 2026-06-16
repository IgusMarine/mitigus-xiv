"""
Agregador de DPS (thread-safe).

Recebe eventos de dano (por ator) e mantém o "encounter" atual: começa no
primeiro dano, e RESETA se ficar idle por `idle_reset` segundos (fim de luta).
Expõe um snapshot pronto pra UI (atores ordenados por dano, com DPS, %, crit/DH).

Os timestamps são em MILISSEGUNDOS (os do bundle, do fio) — consistente com o
analisador offline. DPS = dano / (último - primeiro) da janela ativa.
"""
from __future__ import annotations

import threading
import time

from .names import action_name


class _Actor:
    __slots__ = ("id", "damage", "hits", "crit", "dh", "name", "job", "level", "actions")

    def __init__(self, actor_id):
        self.id = actor_id
        self.damage = 0
        self.hits = 0
        self.crit = 0
        self.dh = 0
        self.name = None
        self.job = None
        self.level = None
        self.actions = {}     # action_id -> dano acumulado (pra "top ability")


class DpsTracker:
    def __init__(self, idle_reset_s: float = 15.0):
        self._lock = threading.Lock()
        self._idle_reset_ms = idle_reset_s * 1000.0
        self._start_ms = None
        self._last_ms = None
        self._actors: dict[int, _Actor] = {}
        self._self_id = None
        self.encounters = 0

    # ---- entrada de dados (chamado pela ponte ao vivo) -------------------
    def record_damage(self, actor_id, value, is_crit=False, is_direct=False,
                      ts_ms=None, action_id=0):
        if value <= 0:
            return
        ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
        with self._lock:
            if self._last_ms is not None and (ts - self._last_ms) > self._idle_reset_ms:
                self._reset_locked()
            if self._start_ms is None:
                self._start_ms = ts
                self.encounters += 1
            self._last_ms = ts
            a = self._actors.get(actor_id)
            if a is None:
                a = self._actors[actor_id] = _Actor(actor_id)
            a.damage += value
            a.hits += 1
            a.crit += int(is_crit)
            a.dh += int(is_direct)
            if action_id:
                a.actions[action_id] = a.actions.get(action_id, 0) + value

    def set_actor_info(self, actor_id, name=None, job=None, level=None):
        with self._lock:
            a = self._actors.get(actor_id)
            if a is None:
                a = self._actors[actor_id] = _Actor(actor_id)
            if name is not None:
                a.name = name
            if job is not None:
                a.job = job
            if level:
                a.level = level

    def mark_self(self, actor_id):
        with self._lock:
            self._self_id = actor_id

    def reset(self):
        with self._lock:
            self._reset_locked()

    def _reset_locked(self):
        self._start_ms = None
        self._last_ms = None
        self._actors = {}

    # ---- saída pra UI ---------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            if self._start_ms is None or self._last_ms is None:
                dur = 0.0
            else:
                dur = max(0.0, (self._last_ms - self._start_ms) / 1000.0)
            total = sum(a.damage for a in self._actors.values())
            rows = []
            for a in sorted(self._actors.values(), key=lambda x: -x.damage):
                if a.damage == 0 and a.hits == 0:
                    continue
                dps = a.damage / dur if dur > 0 else 0.0
                top_id = max(a.actions, key=a.actions.get) if a.actions else 0
                rows.append({
                    "id": a.id,
                    "name": a.name or (f"Você" if a.id == self._self_id else f"{a.id:08X}"),
                    "job": a.job,
                    "level": a.level,
                    "is_self": a.id == self._self_id,
                    "damage": a.damage,
                    "dps": round(dps, 1),
                    "pct": round(100 * a.damage / total, 1) if total else 0.0,
                    "hits": a.hits,
                    "crit": round(100 * a.crit / a.hits, 1) if a.hits else 0.0,
                    "dh": round(100 * a.dh / a.hits, 1) if a.hits else 0.0,
                    "top_action": action_name(top_id) if top_id else None,
                })
            return {
                "active": self._start_ms is not None,
                "duration": round(dur, 1),
                "total_damage": total,
                "total_dps": round(total / dur, 1) if dur > 0 else 0.0,
                "encounters": self.encounters,
                "actors": rows,
            }
