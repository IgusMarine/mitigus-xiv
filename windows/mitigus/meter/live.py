"""
Ponte ao vivo: segmentos do relay -> deob -> parse de combate -> DpsTracker.

`MeterFeed` é um sink de captura (mesma assinatura que o Mitigator espera:
`callable(direction, header, messages)`), então liga direto no relay. Para cada
S2C: acha o pacote inicializador (deriva a chave da rede), e desofusca/parseia
os ActionEffect, somando o dano no tracker.

Também tem `feed_record(rec)` para reprocessar uma captura .jsonl offline com a
MESMA lógica (usado em teste e no analisador).
"""
from __future__ import annotations

from .combat import parse_action_effect, parse_dot_tick
from .names import action_job
from .spawn import parse_npc_spawn, parse_player_spawn
from .tracker import DpsTracker
from ..deob import Deobfuscator
from ..deob.constants import LATEST
from ..protocol.headers import IPC_HEADER_SIZE, XivMessageType

_IPC = int(XivMessageType.Ipc)

_VARIANT_NAMES = (("ActionEffect01", 1), ("ActionEffect08", 8), ("ActionEffect16", 16),
                  ("ActionEffect24", 24), ("ActionEffect32", 32))


class MeterFeed:
    def __init__(self, tracker: DpsTracker = None, version: str = LATEST):
        self.tracker = tracker or DpsTracker()
        self.deob = Deobfuscator(version)
        ops = self.deob.constants.obfuscated_opcodes
        self._init_op = self.deob.constants.unknown_obfuscation_init_opcode
        self._ps_op = ops.get("PlayerSpawn")
        self._ac_op = ops.get("ActorControl")          # tick de DoT (cat 0x605)
        self._status_op = ops.get("StatusEffectList")
        self._status3_op = ops.get("StatusEffectList3")
        self._npc_ops = {op for op in (ops.get("NpcSpawn"), ops.get("NpcSpawn2"))
                         if op is not None}            # pet -> dono
        self._variants = {}
        for name, n in _VARIANT_NAMES:
            op = ops.get(name)
            if op is not None:
                self._variants[op] = n

    # sink do relay -------------------------------------------------------
    def on_segment(self, direction, header, messages) -> None:
        if direction != "s2c":
            return
        ts = int(header.timestamp)
        for mh, md in messages:
            if mh.type_int != _IPC or len(md) < IPC_HEADER_SIZE:
                continue
            self._handle(ts, int(mh.source_actor), int(mh.target_actor), bytes(md))

    __call__ = on_segment

    # reprocesso offline de uma captura .jsonl ----------------------------
    def feed_record(self, rec: dict) -> None:
        if rec.get("dir") != "s2c":
            return
        if "data" not in rec:
            return
        md = bytes.fromhex(rec["data"])
        if len(md) < IPC_HEADER_SIZE:
            return
        self._handle(int(rec.get("ts") or 0), int(rec.get("src") or 0), int(rec.get("tgt") or 0), md)

    # núcleo --------------------------------------------------------------
    def _handle(self, ts, src, tgt, md) -> None:
        op = int.from_bytes(md[2:4], "little")
        if op == self._init_op:
            self.deob.feed_initializer(md)
            return
        if op == self._ac_op:                       # tick de DoT (texto-claro)
            dot = parse_dot_tick(md)
            if dot:
                caster, amount = dot
                # crédito vai pro caster (param3), não pro src (= o alvo). DoT de
                # pet (raro) cai no dono via resolve_pet. count_hit=False: só
                # dano/DPS, sem mexer no crit%/DH% (tick não traz flag de crit).
                self.tracker.record_damage(
                    caster, amount, ts_ms=ts, count_hit=False, resolve_pet=True)
            return
        if not self.deob.is_active:
            return
        if op == self._status_op or op == self._status3_op:
            op_offset = 36 if op == self._status_op else 16
            clean = self.deob.unscramble_copy(md)
            status_list = []
            for i in range(30):
                base = op_offset + i * 12
                if base + 12 > len(clean):
                    break
                status_id = int.from_bytes(clean[base:base+2], "little")
                if status_id == 0:
                    continue
                stacks = clean[base+2]
                import struct
                try:
                    duration = struct.unpack_from("<f", clean, base+4)[0]
                except Exception:
                    duration = 0.0
                caster_id = int.from_bytes(clean[base+8:base+12], "little")
                status_list.append({
                    "status_id": status_id,
                    "stacks": stacks,
                    "duration": duration,
                    "caster_id": caster_id
                })
            self.tracker.update_actor_status(src, status_list, ts)
            return
        if op in self._npc_ops:                     # pet/invocação -> dono
            owner = parse_npc_spawn(self.deob.unscramble_copy(md))
            if owner:
                self.tracker.set_pet_owner(src, owner)
            else:
                self.tracker.clear_pet_owner(src)   # ID reciclada como NPC comum
            return
        if op == self._ps_op:                       # nome + job do ator
            info = parse_player_spawn(self.deob.unscramble_copy(md))
            if info:
                name, job, _, level = info
                self.tracker.set_actor_info(src, name=name, job=job, level=level)
            return
        if op not in self._variants:
            return
        clean = self.deob.unscramble_copy(md)
        ae = parse_action_effect(clean, self._variants[op], segment_target_actor=tgt)
        if ae is None:
            return
        # ações suas têm sequence != 0 (as dos outros chegam como server-originated);
        # é o jeito robusto de marcar "Você", mesmo em party (pet tem seq 0).
        if ae.source_sequence != 0:
            self.tracker.mark_self(src)
        # job dinâmico: infere pela ação usada (Dosis III -> SGE). Sobrevive a
        # troca de gearset sem re-zonar, e cobre os outros da party. NÃO infere
        # pela ação de um pet (resolve(src) != src) p/ não reclassificar o dono.
        if self.tracker.resolve(src) == src:
            aj = action_job(ae.action_id)
            if aj:
                self.tracker.set_actor_info(src, job=aj)
        # dano de pet soma na linha do dono (egi/Bahamut/Queen/fada), resolvido
        # atomicamente dentro do record_damage (resolve_pet).
        for e in ae.effects:
            if e.is_damage:
                self.tracker.record_damage(
                    src, e.value, e.is_crit, e.is_direct, ts_ms=ts,
                    action_id=ae.action_id, resolve_pet=True, target_id=e.target_id)
