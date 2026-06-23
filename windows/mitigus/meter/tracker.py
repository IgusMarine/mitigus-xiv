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

BUFFS = {
    # Damage Multipliers (AoE/Party)
    1878: {"name": "Divination", "type": "mult", "value": 0.06},
    2034: {"name": "Divination", "type": "mult", "value": 0.06},
    1822: {"name": "Technical Finish", "type": "mult", "value": 0.05},
    2050: {"name": "Technical Finish", "type": "mult", "value": 0.05},
    1297: {"name": "Embolden", "type": "mult", "value": 0.05},
    1239: {"name": "Embolden", "type": "mult", "value": 0.05},
    2282: {"name": "Embolden", "type": "mult", "value": 0.05},
    1185: {"name": "Brotherhood", "type": "mult", "value": 0.05},
    2174: {"name": "Brotherhood", "type": "mult", "value": 0.05},
    2703: {"name": "Searing Light", "type": "mult", "value": 0.03},
    2722: {"name": "Radiant Finale", "type": "mult", "value": 0.06},
    2964: {"name": "Radiant Finale", "type": "mult", "value": 0.06},
    3685: {"name": "Starry Muse", "type": "mult", "value": 0.05},
    2599: {"name": "Arcane Circle", "type": "mult", "value": 0.03},  # RPR (id de Status.csv)

    # Target Debuffs (AoE/Party)
    3183: {"name": "Mug", "type": "mult", "value": 0.05, "target": True},
    3849: {"name": "Dokumori", "type": "mult", "value": 0.05, "target": True},
    4303: {"name": "Dokumori", "type": "mult", "value": 0.05, "target": True},
    
    # Single-target Multipliers
    2105: {"name": "Standard Finish", "type": "mult", "value": 0.05, "single": True},
    1821: {"name": "Standard Finish", "type": "mult", "value": 0.05, "single": True},
    2024: {"name": "Standard Finish", "type": "mult", "value": 0.05, "single": True},
    2113: {"name": "Standard Finish", "type": "mult", "value": 0.05, "single": True},
    1882: {"name": "The Balance", "type": "mult", "value": 0.06, "single": True},
    829:  {"name": "The Balance", "type": "mult", "value": 0.06, "single": True},
    1338: {"name": "The Balance", "type": "mult", "value": 0.06, "single": True},
    3887: {"name": "The Balance", "type": "mult", "value": 0.06, "single": True},
    1885: {"name": "The Spear", "type": "mult", "value": 0.06, "single": True},
    832:  {"name": "The Spear", "type": "mult", "value": 0.06, "single": True},
    3889: {"name": "The Spear", "type": "mult", "value": 0.06, "single": True},
    
    # Crit/DH Rate Buffs (AoE/Party)
    786:  {"name": "Battle Litany", "type": "crit", "value": 0.10},
    1414: {"name": "Battle Litany", "type": "crit", "value": 0.10},
    1221: {"name": "Chain Stratagem", "type": "crit", "value": 0.10, "target": True},
    1406: {"name": "Chain Stratagem", "type": "crit", "value": 0.10, "target": True},
    141:  {"name": "Battle Voice", "type": "dh", "value": 0.20},
    
    # Crit/DH Rate Buffs (Single-target / Partner)
    1825: {"name": "Devilment", "type": "crit_dh", "value": 0.20, "single": True},
}

# Constantes da buff-allocation (antes eram números mágicos no record_damage).
CRIT_DMG_MULT = 1.50      # multiplicador de crit (APROX; real ~1.40-1.65 c/ gear)
DH_DMG_MULT = 1.25        # direct hit é FIXO em 1.25 no FFXIV (exato)
_DEFAULT_CRIT_RATE = 0.15
_DEFAULT_DH_RATE = 0.10
_MIN_RATE_SAMPLES = 20    # hits "limpos" (sem buff de crit/DH) p/ confiar na estimativa
_RATE_MIN, _RATE_MAX = 0.05, 0.50   # clamp da taxa base estimada


def _base_rate(hits, hot, default):
    """Estima a taxa BASE de crit/DH do ator pelas amostras 'limpas' (hits sem
    buff de crit/DH ativo). Cai no default até ter amostras suficientes; clampa
    pra faixa sã. (Aproximação: abilities de auto-crit inflam um pouco a taxa.)"""
    if hits >= _MIN_RATE_SAMPLES:
        return min(_RATE_MAX, max(_RATE_MIN, hot / hits))
    return default


class _Actor:
    """Stats de UMA luta (zeram no reset)."""
    __slots__ = ("id", "damage", "hits", "crit", "dh", "actions", "rdps_damage",
                 "adps_damage", "ndps_damage", "cn_hits", "cn_crit", "dn_hits", "dn_dh")

    def __init__(self, actor_id):
        self.id = actor_id
        self.damage = 0
        self.hits = 0
        self.crit = 0
        self.dh = 0
        self.actions = {}     # action_id -> dano acumulado (pra "top ability")
        self.rdps_damage = 0.0
        self.adps_damage = 0.0
        self.ndps_damage = 0.0
        # amostras "limpas" (sem buff de crit/DH) p/ estimar a taxa base do ator
        self.cn_hits = 0
        self.cn_crit = 0
        self.dn_hits = 0
        self.dn_dh = 0


class DpsTracker:
    def __init__(self, idle_reset_s: float = 15.0):
        self._lock = threading.Lock()
        self._idle_reset_ms = idle_reset_s * 1000.0
        self._start_ms = None
        self._last_ms = None
        self._actors: dict[int, _Actor] = {}       # stats da luta (resetável)
        self._info: dict[int, dict] = {}           # identidade (PERSISTENTE)
        self._pet_owner: dict[int, int] = {}       # pet -> dono (PERSISTENTE)
        self._active_status: dict[int, dict[int, dict]] = {}  # actor_id -> status_id -> info (PERSISTENTE)
        self._self_id = None
        self.encounters = 0

    def update_actor_status(self, actor_id, status_list, ts_ms):
        with self._lock:
            actor_status = self._active_status.setdefault(actor_id, {})
            actor_status.clear()
            for s in status_list:
                sid = s["status_id"]
                dur = s["duration"]
                caster = s["caster_id"]
                if dur < 0.0 or dur > 86400.0:
                    end_time = float("inf")
                else:
                    end_time = ts_ms + int(dur * 1000)
                actor_status[sid] = {
                    "caster_id": caster,
                    "stacks": s["stacks"],
                    "end_time_ms": end_time
                }

    def _resolve_caster(self, caster_id):
        return self._pet_owner.get(caster_id, caster_id)

    def _get_active_buffs(self, actor_id, target_id, ts):
        mult_buffs = []
        crit_buffs = []
        dh_buffs = []
        
        # 1. Buffs no atacante
        attacker_status = self._active_status.get(actor_id, {})
        for sid, sinfo in list(attacker_status.items()):
            if ts > sinfo["end_time_ms"]:
                attacker_status.pop(sid, None)
                continue
            bdef = BUFFS.get(sid)
            if bdef:
                if not bdef.get("target"):
                    if bdef["type"] == "mult":
                        mult_buffs.append((bdef, sinfo["caster_id"]))
                    elif bdef["type"] in ("crit", "crit_dh"):
                        crit_buffs.append((bdef, sinfo["caster_id"]))
                    if bdef["type"] in ("dh", "crit_dh"):
                        dh_buffs.append((bdef, sinfo["caster_id"]))
                        
        # 2. Debuffs no alvo (target_id)
        if target_id:
            target_status = self._active_status.get(target_id, {})
            for sid, sinfo in list(target_status.items()):
                if ts > sinfo["end_time_ms"]:
                    target_status.pop(sid, None)
                    continue
                bdef = BUFFS.get(sid)
                if bdef and bdef.get("target"):
                    if bdef["type"] == "mult":
                        mult_buffs.append((bdef, sinfo["caster_id"]))
                    elif bdef["type"] in ("crit", "crit_dh"):
                        crit_buffs.append((bdef, sinfo["caster_id"]))
                    if bdef["type"] in ("dh", "crit_dh"):
                        dh_buffs.append((bdef, sinfo["caster_id"]))
                        
        return mult_buffs, crit_buffs, dh_buffs

    # ---- entrada de dados (chamado pela ponte ao vivo) -------------------
    def record_damage(self, actor_id, value, is_crit=False, is_direct=False,
                      ts_ms=None, action_id=0, count_hit=True, resolve_pet=False, target_id=0):
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
            # taxa base de crit/DH estimada das amostras limpas deste ator
            base_crit = _base_rate(a.cn_hits, a.cn_crit, _DEFAULT_CRIT_RATE)
            base_dh = _base_rate(a.dn_hits, a.dn_dh, _DEFAULT_DH_RATE)

            # --- CÁLCULO DE rDPS, aDPS, nDPS ---
            mult_buffs, crit_buffs, dh_buffs = self._get_active_buffs(actor_id, target_id, ts)
            
            sub_crit = 0.0
            crit_credits = []
            if is_crit and crit_buffs:
                base_val = value / (CRIT_DMG_MULT * DH_DMG_MULT) if is_direct else value / CRIT_DMG_MULT
                g_total = value - base_val
                g_crit = g_total * (2.0 / 3.0) if is_direct else g_total
                sum_crit_val = sum(b["value"] for b, _ in crit_buffs)
                p_crit_total = base_crit + sum_crit_val
                for bdef, caster_id in crit_buffs:
                    resolved_caster = self._resolve_caster(caster_id)
                    if resolved_caster != actor_id and resolved_caster not in (0, 0xE0000000, 0xFFFFFFFF):
                        b_val = bdef["value"]
                        gain = g_crit * (b_val / p_crit_total)
                        sub_crit += gain
                        crit_credits.append((resolved_caster, gain, bdef.get("single", False)))
                        
            sub_dh = 0.0
            dh_credits = []
            if is_direct and dh_buffs:
                base_val = value / (CRIT_DMG_MULT * DH_DMG_MULT) if is_crit else value / DH_DMG_MULT
                g_total = value - base_val
                g_dh = g_total * (1.0 / 3.0) if is_crit else g_total
                sum_dh_val = sum(b["value"] for b, _ in dh_buffs)
                p_dh_total = base_dh + sum_dh_val
                for bdef, caster_id in dh_buffs:
                    resolved_caster = self._resolve_caster(caster_id)
                    if resolved_caster != actor_id and resolved_caster not in (0, 0xE0000000, 0xFFFFFFFF):
                        b_val = bdef["value"]
                        gain = g_dh * (b_val / p_dh_total)
                        sub_dh += gain
                        dh_credits.append((resolved_caster, gain, bdef.get("single", False)))
                        
            net_val = value - sub_crit - sub_dh
            
            ext_mult_buffs = []
            for bdef, caster_id in mult_buffs:
                resolved_caster = self._resolve_caster(caster_id)
                if resolved_caster != actor_id and resolved_caster not in (0, 0xE0000000, 0xFFFFFFFF):
                    ext_mult_buffs.append((bdef, resolved_caster))
                    
            mult_credits = []
            if ext_mult_buffs:
                m_total = 1.0
                for bdef, _ in ext_mult_buffs:
                    m_total *= (1.0 + bdef["value"])
                neutral_val = net_val / m_total
                g_mult = net_val - neutral_val
                sum_mult_val = sum(bdef["value"] for bdef, _ in ext_mult_buffs)
                for bdef, resolved_caster in ext_mult_buffs:
                    gain = g_mult * (bdef["value"] / sum_mult_val)
                    mult_credits.append((resolved_caster, gain, bdef.get("single", False)))
            else:
                neutral_val = net_val
                
            a.damage += value
            a.rdps_damage += neutral_val
            a.ndps_damage += neutral_val
            
            m_single_ext = 1.0
            m_total = 1.0
            for bdef, resolved_caster in ext_mult_buffs:
                m_total *= (1.0 + bdef["value"])
                if bdef.get("single"):
                    m_single_ext *= (1.0 + bdef["value"])
            
            a_crit_dh_gain = 0.0
            for resolved_caster, gain, is_single in crit_credits + dh_credits:
                if not is_single:
                    a_crit_dh_gain += gain
                    
            a.adps_damage += (neutral_val * (m_total / m_single_ext)) + a_crit_dh_gain
            
            for resolved_caster, gain, _ in crit_credits + dh_credits + mult_credits:
                c_actor = self._actors.get(resolved_caster)
                if c_actor is None:
                    c_actor = self._actors[resolved_caster] = _Actor(resolved_caster)
                c_actor.rdps_damage += gain

            if count_hit:
                a.hits += 1
                a.crit += int(is_crit)
                a.dh += int(is_direct)
                # amostra "limpa" p/ a taxa base: só conta quando NÃO há buff de
                # crit/DH ativo neste hit (self ou externo).
                if not crit_buffs:
                    a.cn_hits += 1
                    a.cn_crit += int(is_crit)
                if not dh_buffs:
                    a.dn_hits += 1
                    a.dn_dh += int(is_direct)
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
            for a in sorted(self._actors.values(), key=lambda x: -max(x.damage, x.rdps_damage)):
                if a.damage == 0 and a.hits == 0 and a.rdps_damage == 0.0:
                    continue
                info = self._info.get(a.id, {})
                dps = a.damage / dur if dur > 0 else 0.0
                rdps = a.rdps_damage / dur if dur > 0 else 0.0
                adps = a.adps_damage / dur if dur > 0 else 0.0
                ndps = a.ndps_damage / dur if dur > 0 else 0.0
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
                    "rdps": round(rdps, 1),
                    "adps": round(adps, 1),
                    "ndps": round(ndps, 1),
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
