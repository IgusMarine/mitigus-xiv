"""
Agregador de DPS (thread-safe).

Recebe eventos de dano (por ator) e mantém o "encounter" atual: começa no
primeiro dano, e RESETA se ficar idle por `idle_reset` segundos (fim de luta).
Expõe um snapshot pronto pra UI (atores ordenados por dano, com DPS, %, crit/DH).

IDENTIDADE x STATS: o nome/job/level de cada ator é PERSISTENTE (vem do
PlayerSpawn, que é raro, e do job inferido pelas ações). As estatísticas de dano
são por-encounter e zeram no reset. Por isso identidade e stats ficam em mapas
separados — senão a troca de luta apagaria o job/nome (bug observado).

Os timestamps são em MILISSEGUNDOS (os do bundle, do fio). DPS = dano / (último
- primeiro) da janela ativa.
"""
from __future__ import annotations

import threading
import time

from .names import action_name


class _Actor:
    """Stats de UMA luta (zeram no reset)."""
    __slots__ = ("id", "damage", "hits", "crit", "dh", "actions")

    def __init__(self, actor_id):
        self.id = actor_id
        self.damage = 0
        self.hits = 0
        self.crit = 0
        self.dh = 0
        self.actions = {}     # action_id -> dano acumulado (pra "top ability")


class DpsTracker:
    def __init__(self, idle_reset_s: float = 15.0):
        self._lock = threading.Lock()
        self._idle_reset_ms = idle_reset_s * 1000.0
        self._start_ms = None
        self._last_ms = None
        self._actors: dict[int, _Actor] = {}       # stats da luta (resetável)
        self._info: dict[int, dict] = {}           # identidade (PERSISTENTE)
        self._pet_owner: dict[int, int] = {}       # pet -> dono (PERSISTENTE)
        self._self_id = None
        self.encounters = 0

    # ---- entrada de dados (chamado pela ponte ao vivo) -------------------
    def record_damage(self, actor_id, value, is_crit=False, is_direct=False,
                      ts_ms=None, action_id=0, count_hit=True, resolve_pet=False):
        # count_hit=False (tick de DoT): soma no dano/DPS mas NÃO conta como hit
        # — o pacote do tick não traz flag de crit/DH, então contá-lo poluiria o
        # crit%/DH% (que devem refletir os golpes diretos, como no ACT).
        # resolve_pet=True: resolve pet->dono AQUI DENTRO do lock, pra atribuição
        # não correr com um set_pet_owner concorrente (TOCTOU).
        if value <= 0:
            return
        ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
        with self._lock:
            if resolve_pet:
                actor_id = self._pet_owner.get(actor_id, actor_id)
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
            if count_hit:
                a.hits += 1
                a.crit += int(is_crit)
                a.dh += int(is_direct)
            if action_id:
                a.actions[action_id] = a.actions.get(action_id, 0) + value

    def set_actor_info(self, actor_id, name=None, job=None, level=None):
        # identidade é PERSISTENTE — sobrevive ao reset de luta.
        with self._lock:
            info = self._info.setdefault(actor_id, {})
            if name is not None:
                info["name"] = name
            if job is not None:
                info["job"] = job
            if level:
                info["level"] = level

    def mark_self(self, actor_id):
        with self._lock:
            self._self_id = actor_id

    def set_pet_owner(self, pet_id, owner_id):
        # pet (egi/Bahamut/Queen/fada) -> dono. PERSISTENTE: sobrevive ao reset,
        # senão o dano do pet voltaria a virar uma linha-fantasma na luta nova.
        if owner_id and pet_id and pet_id != owner_id:
            with self._lock:
                self._pet_owner[pet_id] = owner_id

    def clear_pet_owner(self, actor_id):
        # ID reciclada como NPC comum (FFXIV reusa GameObjectIds): some o
        # mapeamento antigo, senão o dano do novo NPC seria creditado ao dono
        # do pet que tinha essa ID. Chamado quando chega NpcSpawn com owner=0.
        with self._lock:
            self._pet_owner.pop(actor_id, None)

    def resolve(self, actor_id):
        # se for um pet conhecido, devolve o dono; senão o próprio ator. Assim o
        # dano do pet/DoT soma na linha do dono em vez de criar um ator separado.
        with self._lock:
            return self._pet_owner.get(actor_id, actor_id)

    def reset(self):
        # zera só a luta; mantém identidade (você continua sendo você).
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
                info = self._info.get(a.id, {})
                dps = a.damage / dur if dur > 0 else 0.0
                top_id = max(a.actions, key=a.actions.get) if a.actions else 0
                rows.append({
                    "id": a.id,
                    "name": info.get("name") or (
                        "Você" if a.id == self._self_id else f"{a.id:08X}"),
                    "job": info.get("job"),
                    "level": info.get("level"),
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
