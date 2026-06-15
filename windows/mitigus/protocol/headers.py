"""
FFXIV binary protocol: headers and constants.

Portado fiel do Soreepeong/XivMitmLatencyMitigator (mitigate.py) para que o
engine Windows fale exatamente o mesmo formato de fio. Os nomes dos campos
espelham o upstream de propósito, para que o port futuro do resto da lógica
encaixe sem tradução.

Enquadramento (3 camadas aninhadas):
    bundle  ->  uma ou mais messages (segments)  ->  payload IPC (quando type==Ipc)

O header do bundle (40 bytes) vai SEMPRE descomprimido. O CORPO do bundle (todas
as messages concatenadas) pode estar comprimido em zlib ou Oodle, conforme o
campo `compression`.
"""
from __future__ import annotations

import ctypes
import enum

# Um bundle de jogo real começa com este magic de 16 bytes. Keepalives e alguns
# bundles de controle usam um magic todo-zero. Ambos marcam uma fronteira válida.
BUNDLE_MAGIC = b"\x52\x52\xa0\x41\xff\x5d\x46\xe2\x7f\x2a\x64\x4d\x7b\x99\xc4\x75"
BUNDLE_MAGIC_ZERO = b"\x00" * 16
BUNDLE_MAX_LENGTH = 65536


class XivBundleHeader(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = (
        ("magic", ctypes.c_ubyte * 16),
        ("timestamp", ctypes.c_uint64),        # ms desde a época unix
        ("length", ctypes.c_uint32),           # bundle inteiro, incluindo este header
        ("conn_type", ctypes.c_uint16),        # 1=zone, 2=chat
        ("message_count", ctypes.c_uint16),
        ("encoding", ctypes.c_uint8),
        ("compression", ctypes.c_uint8),       # 0=none, 1=zlib, 2=oodle
        ("unknown_0x022", ctypes.c_uint16),
        ("decoded_body_length", ctypes.c_uint32),
    )

    def magic_bytes(self) -> bytes:
        return bytes(self.magic)

    def has_valid_magic(self) -> bool:
        m = bytes(self.magic)
        return m == BUNDLE_MAGIC or m == BUNDLE_MAGIC_ZERO


class XivMessageType(enum.IntEnum):
    Ipc = 3


class XivMessageIpcType(enum.IntEnum):
    UnknownButInterested = 0x0014           # marca de mensagem IPC de jogo "interessante"
    XivMitmLatencyMitigatorCustom = 0xE852  # nosso IPC custom (OriginalWaitTime)


class XivMessageHeader(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = (
        ("length", ctypes.c_uint32),
        ("source_actor", ctypes.c_uint32),
        ("target_actor", ctypes.c_uint32),
        ("type_int", ctypes.c_uint16),
        ("unknown_0x00e", ctypes.c_uint16),
    )

    @property
    def type(self):
        try:
            return XivMessageType(self.type_int)
        except ValueError:
            return None

    @type.setter
    def type(self, value):
        self.type_int = int(value)


class XivMessageIpcHeader(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = (
        ("type_int", ctypes.c_uint16),   # marca (0x0014 = interessante); NÃO é o opcode
        ("subtype", ctypes.c_uint16),    # <- o opcode de verdade
        ("unknown_0x004", ctypes.c_uint16),
        ("server_id", ctypes.c_uint16),
        ("epoch", ctypes.c_uint32),
        ("unknown_0x00c", ctypes.c_uint32),
    )

    @property
    def type(self):
        try:
            return XivMessageIpcType(self.type_int)
        except ValueError:
            return None

    @type.setter
    def type(self, value):
        self.type_int = int(value)


class Compression(enum.IntEnum):
    NONE = 0
    ZLIB = 1
    OODLE = 2


class ConnType(enum.IntEnum):
    ZONE = 1
    CHAT = 2


BUNDLE_HEADER_SIZE = ctypes.sizeof(XivBundleHeader)     # 40
MESSAGE_HEADER_SIZE = ctypes.sizeof(XivMessageHeader)   # 16
IPC_HEADER_SIZE = ctypes.sizeof(XivMessageIpcHeader)    # 16

# Sanidade: se alguma dessas falhar, o alinhamento do ctypes divergiu do fio.
assert BUNDLE_HEADER_SIZE == 40, BUNDLE_HEADER_SIZE
assert MESSAGE_HEADER_SIZE == 16, MESSAGE_HEADER_SIZE
assert IPC_HEADER_SIZE == 16, IPC_HEADER_SIZE
