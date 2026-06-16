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

from .combat import parse_action_effect
from .spawn import parse_player_spawn
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
        self._init_op = self.deob.constants.unknown_obfuscation_init_opcode
        self._ps_op = self.deob.constants.obfuscated_opcodes.get("PlayerSpawn")
        self._variants = {}
        for name, n in _VARIANT_NAMES:
            op = self.deob.constants.obfuscated_opcodes.get(name)
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
            self._handle(ts, int(mh.source_actor), bytes(md))

    __call__ = on_segment

    # reprocesso offline de uma captura .jsonl ----------------------------
    def feed_record(self, rec: dict) -> None:
        if rec.get("dir", "s2c") != "s2c":
            return
        md = bytes.fromhex(rec["data"])
        if len(md) < IPC_HEADER_SIZE:
            return
        self._handle(int(rec.get("ts", 0)), int(rec.get("src", 0)), md)

    # núcleo --------------------------------------------------------------
    def _handle(self, ts, src, md) -> None:
        op = int.from_bytes(md[2:4], "little")
        if op == self._init_op:
            self.deob.feed_initializer(md)
            return
        if not self.deob.is_active:
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
        ae = parse_action_effect(clean, self._variants[op])
        if ae is None:
            return
        # ações suas têm sequence != 0 (as dos outros chegam como server-originated);
        # é o jeito robusto de marcar "Você", mesmo em party.
        if ae.source_sequence != 0:
            self.tracker.mark_self(src)
        for e in ae.effects:
            if e.is_damage:
                self.tracker.record_damage(
                    src, e.value, e.is_crit, e.is_direct, ts_ms=ts,
                    action_id=ae.action_id)
