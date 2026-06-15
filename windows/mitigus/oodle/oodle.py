"""
Codec Oodle Network do FFXIV — port Windows-nativo do `mitigate.py` (Fase 3).

Desde o patch 6.3 (e no Dawntrail/7.x) o corpo dos bundles é comprimido com
OodleNetwork1 TCP, que mantém ESTADO por conexão: para decodificar um pacote é
preciso ter processado todos os anteriores daquele canal, desde o início. Por
isso a captura precisa começar antes/junto do login, sem perda.

O Oodle vem estaticamente ligado dentro do `ffxiv_dx11.exe`. Carregamos o PE à
mão (pe.PeImage), localizamos as funções por sigscan no `.text`, e as chamamos.

DIFERENÇA-CHAVE vs. o original (Linux): o `mitigate.py` constrói thunks de
conversão de ABI stdcall->cdecl porque o Linux não chama a ABI do Windows
nativamente. AQUI, no Windows x64, a ABI já é a nativa — usamos `ctypes.WINFUNCTYPE`
e chamamos direto, sem thunk nenhum.

   Requer `ffxiv_dx11.exe` (x64). Use run_oodle_test.py para validar.
"""
from __future__ import annotations

import ctypes
import pathlib
import re
import sys
import typing

from .pe import POINTER_SIZE, PeImage

UDP_CHANNEL = 0xFFFFFFFF
TCP_CHANNELS = (0, 1, 2, 3)

WF = ctypes.WINFUNCTYPE  # em x64 há uma só convenção de chamada (== CFUNCTYPE)

# Assinaturas das funções Oodle (idênticas às do mitigate.py).
_T_SharedSize = WF(ctypes.c_int32, ctypes.c_int32)
_T_SharedSetWindow = WF(None, ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p, ctypes.c_int32)
_T_Train = WF(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
              ctypes.POINTER(ctypes.c_int32), ctypes.c_int32)
_T_Decode = WF(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
               ctypes.c_void_p, ctypes.c_size_t)
_T_Encode = WF(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
               ctypes.c_void_p)
_T_StateSize = WF(ctypes.c_int32)
_T_SetMallocFree = WF(None, ctypes.c_void_p, ctypes.c_void_p)

_MallocCb = WF(ctypes.c_size_t, ctypes.c_size_t, ctypes.c_int32)
_FreeCb = WF(None, ctypes.c_size_t)

_msvcrt = ctypes.CDLL("msvcrt")
_crt_malloc = _msvcrt.malloc
_crt_malloc.argtypes = (ctypes.c_size_t,)
_crt_malloc.restype = ctypes.c_size_t
_crt_free = _msvcrt.free
_crt_free.argtypes = (ctypes.c_size_t,)


def _oodle_malloc(size: int, align: int) -> int:
    raw = _crt_malloc(size + align + POINTER_SIZE - 1)
    if raw == 0:
        return 0
    aligned = (raw + align + POINTER_SIZE - 1) & ((~align & (sys.maxsize * 2 + 1)) + 1)
    ctypes.c_void_p.from_address(aligned - POINTER_SIZE).value = raw
    return aligned


def _oodle_free(aligned: int) -> None:
    _crt_free(ctypes.c_void_p.from_address(aligned - POINTER_SIZE).value)


class OodleModule:
    """Localiza e expõe as funções Oodle dentro de um PE (ffxiv_dx11.exe x64)."""

    def __init__(self, image: PeImage):
        if POINTER_SIZE != 8:
            raise RuntimeError("Oodle: requer Python 64-bit (x64).")
        self._image = image
        text = image.section_header(b".text")
        text_view = image.section(text)

        def rip(group_start: int) -> int:
            return image.address.value + image.resolve_rip_relative(text.VirtualAddress + group_start - 1)

        # --- InitOodle: set_malloc_free, htbits, shared_size, window, shared_set_window
        pattern = (br"\x75.\x48\x8d\x15....\x48\x8d\x0d....\xe8(....)\xc6\x05....\x01.{0,256}"
                   br"\x75.\xb9(....)\xe8(....)\x45\x33\xc0\x33\xd2\x48\x8b\xc8\xe8.....{0,6}"
                   br"\x41\xb9(....)\xba.....{0,6}\x48\x8b\xc8\xe8(....)")
        m = re.search(pattern, text_view, re.DOTALL)
        if not m:
            raise RuntimeError("Could not find InitOodle.")
        self.set_malloc_free_address = rip(m.start(1))
        self.htbits = int.from_bytes(m.group(2), "little")
        self.shared_size_address = rip(m.start(3))
        self.window = int.from_bytes(m.group(4), "little")
        self.shared_set_window_address = rip(m.start(5))

        # --- SetUpStatesAndTrain: udp/tcp state size, tcp/udp train
        pattern = (br"\x75\x04\x48\x89..\xe8(....)\x4c..\xe8(....).{0,256}\x01\x75\x0a\x48\x8b."
                   br"\xe8(....)\xeb\x09\x48\x8b.\x08\xe8(....)")
        m = re.search(pattern, text_view, re.DOTALL)
        if not m:
            raise RuntimeError("Could not find SetUpStatesAndTrain.")
        self.udp_state_size_address = rip(m.start(1))
        self.tcp_state_size_address = rip(m.start(2))
        self.tcp_train_address = rip(m.start(3))
        self.udp_train_address = rip(m.start(4))

        # --- Tcp/UdpDecode
        m = re.search(br"\x4d\x85\xd2\x74\x0a\x49\x8b\xca\xe8(....)\xeb\x09\x48\x8b\x49\x08\xe8(....)",
                      text_view, re.DOTALL)
        if not m:
            raise RuntimeError("Could not find Tcp/UdpDecode.")
        self.tcp_decode_address = rip(m.start(1))
        self.udp_decode_address = rip(m.start(2))

        # --- Tcp/UdpEncode
        m = re.search(br"\x48\x85\xc0\x74\x0d\x48\x8b\xc8\xe8(....)\x48..\xeb\x0b\x48\x8b\x49\x08\xe8(....)",
                      text_view, re.DOTALL)
        if not m:
            raise RuntimeError("Could not find Tcp/UdpEncode.")
        self.tcp_encode_address = rip(m.start(1))
        self.udp_encode_address = rip(m.start(2))

        # Constrói os ponteiros de função (chamada nativa Windows, sem thunk de ABI).
        self.set_malloc_free = _T_SetMallocFree(self.set_malloc_free_address)
        self.shared_size = _T_SharedSize(self.shared_size_address)
        self.shared_set_window = _T_SharedSetWindow(self.shared_set_window_address)
        self.udp_state_size = _T_StateSize(self.udp_state_size_address)
        self.tcp_state_size = _T_StateSize(self.tcp_state_size_address)
        self.tcp_train = _T_Train(self.tcp_train_address)
        self.udp_train = _T_Train(self.udp_train_address)
        self.tcp_decode = _T_Decode(self.tcp_decode_address)
        self.udp_decode = _T_Decode(self.udp_decode_address)
        self.tcp_encode = _T_Encode(self.tcp_encode_address)
        self.udp_encode = _T_Encode(self.udp_encode_address)

        # Neutraliza o _alloca_probe (a imagem mapeada não tem o CRT ligado).
        m = re.search(br"\x48\x83\xec\x10\x4c\x89\x14\x24\x4c\x89\x5c\x24\x08\x4d\x33\xdb", text_view)
        if not m:
            raise RuntimeError("_alloca_probe not found")
        image.view[text.VirtualAddress + m.start(0)] = 0xC3  # ret

        # Instala nosso malloc/free alinhado. Mantém referências vivas (Oodle guarda os ponteiros).
        self._malloc_cb = _MallocCb(_oodle_malloc)
        self._free_cb = _FreeCb(_oodle_free)
        self.set_malloc_free(
            ctypes.cast(self._malloc_cb, ctypes.c_void_p).value,
            ctypes.cast(self._free_cb, ctypes.c_void_p).value,
        )

    @classmethod
    def from_exe(cls, exe_path: str) -> "OodleModule":
        return cls(PeImage(pathlib.Path(exe_path).read_bytes()))


class OodleInstance:
    """Estado de UM canal (uma direção de uma conexão). TCP é stateful."""

    def __init__(self, module: OodleModule, use_tcp: bool):
        self._state = (ctypes.c_uint8 * (module.tcp_state_size() if use_tcp else module.udp_state_size()))()
        self._shared = (ctypes.c_uint8 * module.shared_size(module.htbits))()
        self._window = (ctypes.c_uint8 * module.window)()
        module.shared_set_window(
            ctypes.addressof(self._shared), module.htbits,
            ctypes.addressof(self._window), len(self._window),
        )
        (module.tcp_train if use_tcp else module.udp_train)(
            ctypes.addressof(self._state),
            ctypes.addressof(self._shared),
            ctypes.POINTER(ctypes.c_void_p)(),
            ctypes.POINTER(ctypes.c_int32)(),
            0,
        )
        self._encode_function = module.tcp_encode if use_tcp else module.udp_encode
        self._decode_function = module.tcp_decode if use_tcp else module.udp_decode

    def encode(self, src: typing.Union[bytes, bytearray, memoryview]) -> bytearray:
        if not isinstance(src, (bytearray, memoryview)):
            src = bytearray(src)
        if len(src) == 0:
            return bytearray()
        enc = bytearray(len(src) + 8)
        written = self._encode_function(
            ctypes.addressof(self._state),
            ctypes.addressof(self._shared),
            ctypes.addressof(ctypes.c_byte.from_buffer(src)), len(src),
            ctypes.addressof(ctypes.c_byte.from_buffer(enc)),
        )
        del enc[written:]
        return enc

    def decode(self, enc: typing.Union[bytes, bytearray, memoryview], result_length: int) -> bytearray:
        if result_length == 0:
            return bytearray()
        if not isinstance(enc, (bytearray, memoryview)):
            enc = bytearray(enc)
        dec = bytearray(result_length)
        ok = self._decode_function(
            ctypes.addressof(self._state),
            ctypes.addressof(self._shared),
            ctypes.addressof(ctypes.c_byte.from_buffer(enc)), len(enc),
            ctypes.addressof(ctypes.c_byte.from_buffer(dec)), len(dec),
        )
        if not ok:
            raise RuntimeError("Oodle decode fail")
        return dec


class OodleHelper:
    """5 canais como o original: UDP (0xFFFFFFFF) + TCP 0..3."""

    def __init__(self, module: OodleModule):
        self.module = module
        self.channels = {UDP_CHANNEL: OodleInstance(module, False)}
        for ch in TCP_CHANNELS:
            self.channels[ch] = OodleInstance(module, True)

    @classmethod
    def from_exe(cls, exe_path: str) -> "OodleHelper":
        return cls(OodleModule.from_exe(exe_path))

    def encode(self, channel: int, data: bytes) -> bytes:
        return bytes(self.channels[channel].encode(data))

    def decode(self, channel: int, data: bytes, declen: int) -> bytes:
        return bytes(self.channels[channel].decode(data, declen))


def selftest(helper: OodleHelper) -> bool:
    """Round-trip TCP e UDP, igual ao test_oodle() do mitigate.py."""
    testval = b"\x00\x00\x00\x04\x00\x00\x00\x04\x00\x00\x00\x04\x00\x00\x00\x04" * 16
    enc = helper.encode(0, testval)
    dec = helper.decode(1, enc, len(testval))
    if dec != testval:
        return False
    enc = helper.encode(UDP_CHANNEL, testval)
    dec = helper.decode(UDP_CHANNEL, enc, len(testval))
    return dec == testval
