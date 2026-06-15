"""
Structs de payload IPC e constantes da mitigação — port fiel do `mitigate.py`.

São os corpos das mensagens IPC que a Fase 4 lê/reescreve: o ActionRequest
(cliente->servidor), o ActionEffect (servidor->cliente, onde fica o
`animation_lock_duration`), ActorCast/ActorControl/ActorControlSelf (para saber
quando uma ação virou cast, foi cancelada ou rejeitada), e o nosso IPC custom
`OriginalWaitTime` (preserva o valor original, auditável).

O opcode de uma mensagem IPC é o campo `subtype` do XivMessageIpcHeader; o
`type_int` é só a marca 0x0014 ("interessante").
"""
from __future__ import annotations

import ctypes
import enum
import typing

# Constantes (valores do mitigate.py).
AUTO_ATTACK_DELAY = 0.1
ACTION_ID_AUTO_ATTACK = 0x0007
ACTION_ID_AUTO_ATTACK_MCH = 0x0008
DEFAULT_EXTRA_DELAY = 0.075  # margem de segurança. NÃO diminua. Você foi avisado.

T = typing.TypeVar("T")


def clamp(v: T, min_: T, max_: T) -> T:
    return max(min_, min(max_, v))


class XivMessageIpcActorControlCategory(enum.IntEnum):
    CancelCast = 0x000F
    Rollback = 0x02BC


class XivMitmLatencyMitigatorCustomSubtype(enum.IntEnum):
    OriginalWaitTime = 0x0000


class XivMessageIpcActionEffect(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = (
        ("animation_target_actor", ctypes.c_uint32),
        ("unknown_0x004", ctypes.c_uint32),
        ("action_id", ctypes.c_uint32),
        ("global_effect_counter", ctypes.c_uint32),
        ("animation_lock_duration", ctypes.c_float),
        ("unknown_target_id", ctypes.c_uint32),
        ("source_sequence", ctypes.c_uint16),
        ("rotation", ctypes.c_uint16),
        ("action_animation_id", ctypes.c_uint16),
        ("variation", ctypes.c_uint8),
        ("effect_display_type", ctypes.c_uint8),
        ("unknown_0x020", ctypes.c_uint8),
        ("effect_count", ctypes.c_uint8),
        ("padding_0x022", ctypes.c_uint16),
    )


class XivMessageIpcActorControl(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = (
        ("category_int", ctypes.c_uint16),
        ("padding_0x002", ctypes.c_uint16),
        ("param_1", ctypes.c_uint32),
        ("param_2", ctypes.c_uint32),
        ("param_3", ctypes.c_uint32),
        ("param_4", ctypes.c_uint32),
        ("padding_0x014", ctypes.c_uint32),
    )

    @property
    def category(self):
        try:
            return XivMessageIpcActorControlCategory(self.category_int)
        except ValueError:
            return None


class XivMessageIpcActorControlSelf(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = (
        ("category_int", ctypes.c_uint16),
        ("padding_0x002", ctypes.c_uint16),
        ("param_1", ctypes.c_uint32),
        ("param_2", ctypes.c_uint32),
        ("param_3", ctypes.c_uint32),
        ("param_4", ctypes.c_uint32),
        ("param_5", ctypes.c_uint32),
        ("param_6", ctypes.c_uint32),
        ("padding_0x01c", ctypes.c_uint32),
        ("padding_0x020", ctypes.c_uint32),
        ("padding_0x024", ctypes.c_uint32),
    )

    @property
    def category(self):
        try:
            return XivMessageIpcActorControlCategory(self.category_int)
        except ValueError:
            return None


class XivMessageIpcActorCast(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = (
        ("action_id", ctypes.c_uint16),
        ("skill_type", ctypes.c_uint8),
        ("unknown_0x003", ctypes.c_uint8),
        ("action_id_2", ctypes.c_uint16),
        ("unknown_0x006", ctypes.c_uint16),
        ("cast_time", ctypes.c_float),
        ("target_id", ctypes.c_uint32),
        ("rotation", ctypes.c_float),
        ("unknown_0x014", ctypes.c_uint32),
        ("x", ctypes.c_uint16),
        ("y", ctypes.c_uint16),
        ("z", ctypes.c_uint16),
        ("unknown_0x01e", ctypes.c_uint16),
    )


class XivMessageIpcActionRequestCommon(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = (
        ("action_id", ctypes.c_uint32),
        ("unknown_0x002", ctypes.c_uint16),
        ("sequence", ctypes.c_uint16),
    )


class XivMessageIpcCustomOriginalWaitTime(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = (
        ("source_sequence", ctypes.c_uint16),
        ("padding_0x002", ctypes.c_uint16),
        ("original_wait_time", ctypes.c_float),
    )
