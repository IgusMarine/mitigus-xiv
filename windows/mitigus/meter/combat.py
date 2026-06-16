"""
Parser de combate: ActionEffect (já desofuscado) -> efeitos (dano/cura/etc.).

Layout VALIDADO contra captura real (luta.jsonl, patch 2026.06.10), lendo os
bytes do pacote desofuscado:

  buffer (a partir do HEADER IPC, 16B):
    +24  action_id        (u32)   [vinha ofuscado; já desofuscado aqui]
    +32  animation_lock   (float)
    +40  source_sequence  (u16)
    +49  effect_count     (u8)    = nº de alvos afetados
    +58  array de EffectEntry: [effect_count alvos][8 slots], 8 bytes cada
         entry (Sapphire Common.h struct EffectEntry, = FFXIVClientStructs):
           type@0  severity@1  param1@2  param2@3  extValueHighByte@4
           flags@5  value(u16)@6
         (ex. real: GCD -> type=0x03, value@6 = dano)

Offsets/layout ANCORADOS em fonte canônica (Sapphire ServerZoneDef.h/Common.h +
aers/FFXIVClientStructs), confirmados byte-a-byte contra a captura real
(luta.jsonl): severity@1 variou 0x00/0x20/0x40/0x60 = crit(0x20)/DH(0x40)/ambos.

Tipos (enum ActionEffectType — Sapphire Common.h, confirmado p/ cactbot):
0x03 Damage, 0x05 BlockedDamage, 0x06 ParriedDamage = DANO; 0x04 Heal;
0x0F ApplyStatusEffectTarget / 0x10 ApplyStatusEffectSource (value = ID do
status, NÃO é dano); 0x1B StartActionCombo (combo, não é dano). Só 0x03/0x05/
0x06 entram no DPS. (0x19/0x1B NÃO são dano — eram chute meu; fonte desmente.)

Dano > 65535 (Sapphire extendedValueHighestByte + cactbot flag 0x4000): se
flags(byte@5) & 0x40, o dano real = (byte@4 << 16) | value(u16). Implementado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

IPC_HEADER_SIZE = 16

OFF_ACTION_ID = 24
OFF_ANIM_LOCK = 32
OFF_SOURCE_SEQ = 40
OFF_EFFECT_COUNT = 49
EFFECTS_AT = 58            # início do array de EffectEntry (buffer)
ENTRY_SIZE = 8
SLOTS_PER_TARGET = 8

# Tipos de efeito (FFXIV). Os de dano somam pro DPS.
EFFECT_DAMAGE = 0x03
EFFECT_BLOCKED = 0x05      # dano bloqueado (ainda é dano)
EFFECT_PARRIED = 0x06      # dano aparado (ainda é dano)
EFFECT_HEAL = 0x04
DAMAGE_TYPES = frozenset((EFFECT_DAMAGE, EFFECT_BLOCKED, EFFECT_PARRIED))

# bits de severidade do golpe (no byte de severidade)
SEV_CRIT = 0x20
SEV_DIRECT = 0x40


def _u16(b, o):
    return int.from_bytes(b[o:o + 2], "little")


def _u32(b, o):
    return int.from_bytes(b[o:o + 4], "little")


def _f32(b, o):
    import struct
    return struct.unpack_from("<f", b, o)[0]


@dataclass
class Effect:
    target_index: int
    type: int
    severity: int
    flags: int
    value: int

    @property
    def is_damage(self) -> bool:
        return self.type in DAMAGE_TYPES

    @property
    def is_heal(self) -> bool:
        return self.type == EFFECT_HEAL

    @property
    def is_crit(self) -> bool:
        return bool(self.severity & SEV_CRIT)

    @property
    def is_direct(self) -> bool:
        return bool(self.severity & SEV_DIRECT)


@dataclass
class ActionEffectResult:
    action_id: int
    source_sequence: int
    animation_lock: float
    effect_count: int
    effects: List[Effect] = field(default_factory=list)

    @property
    def total_damage(self) -> int:
        return sum(e.value for e in self.effects if e.is_damage)


def parse_action_effect(md: bytes, max_targets: int) -> Optional[ActionEffectResult]:
    """
    Interpreta um ActionEffect DESOFUSCADO (buffer a partir do header IPC).
    `max_targets` é o teto do variante (1/8/16/24/32). Retorna None se truncado.
    """
    if len(md) < EFFECTS_AT:
        return None
    action_id = _u32(md, OFF_ACTION_ID)
    seq = _u16(md, OFF_SOURCE_SEQ)
    anim = _f32(md, OFF_ANIM_LOCK)
    count = md[OFF_EFFECT_COUNT]
    n_targets = min(count, max_targets) if count else 0

    res = ActionEffectResult(action_id, seq, anim, count)
    for t in range(n_targets):
        base = EFFECTS_AT + t * SLOTS_PER_TARGET * ENTRY_SIZE
        for s in range(SLOTS_PER_TARGET):
            off = base + s * ENTRY_SIZE
            if off + ENTRY_SIZE > len(md):
                break
            etype = md[off]
            if etype == 0:
                continue  # slot vazio
            value = _u16(md, off + 6)
            flags = md[off + 5]
            if flags & 0x40:                # dano > 65535 (flag 0x4000)
                value |= md[off + 4] << 16  # byte alto = extendedValueHighestByte
            res.effects.append(Effect(
                target_index=t,
                type=etype,
                severity=md[off + 1],   # 0x20=crit, 0x40=direct-hit, 0x60=ambos
                flags=flags,
                value=value,
            ))
    return res
