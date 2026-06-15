"""
Reassembler de stream e leitura de bundles do FFXIV.

`BundleStream` acumula os bytes de payload TCP de UMA direção de UM fluxo e
entrega bundles completos conforme eles chegam, ressincronizando no magic se a
captura começar no meio do stream (ou pegar lixo). Como TCP é por-fluxo, é assim
que lidamos com bundles que cruzam fronteiras de segmento ou que vêm vários
empacotados num único segmento.

`decode_body` / `iter_messages` / `read_opcode` desempacotam o corpo do bundle.
Oodle (compression==2) ainda NÃO é suportado aqui — isso é a Fase 3 (carregar o
codec do ffxiv_dx11.exe). Para esses bundles devolvemos None e o chamador apenas
os contabiliza.
"""
from __future__ import annotations

import zlib
from typing import Iterator, Optional, Tuple

from .headers import (
    BUNDLE_HEADER_SIZE,
    BUNDLE_MAGIC,
    BUNDLE_MAX_LENGTH,
    IPC_HEADER_SIZE,
    MESSAGE_HEADER_SIZE,
    Compression,
    XivBundleHeader,
    XivMessageHeader,
    XivMessageIpcHeader,
    XivMessageType,
)


class BundleStream:
    def __init__(self) -> None:
        self._buf = bytearray()
        self._synced = False

    def feed(self, data: bytes) -> None:
        if data:
            self._buf.extend(data)

    def __iter__(self) -> Iterator[Tuple[XivBundleHeader, bytes]]:
        buf = self._buf
        while True:
            if not self._synced:
                idx = buf.find(BUNDLE_MAGIC)
                if idx < 0:
                    # mantém uma cauda caso o magic atravesse o próximo chunk
                    tail = len(BUNDLE_MAGIC) - 1
                    if len(buf) > tail:
                        del buf[: len(buf) - tail]
                    return
                del buf[:idx]
                self._synced = True

            if len(buf) < BUNDLE_HEADER_SIZE:
                return

            header = XivBundleHeader.from_buffer_copy(bytes(buf[:BUNDLE_HEADER_SIZE]))
            length = header.length
            if (
                not header.has_valid_magic()
                or length < BUNDLE_HEADER_SIZE
                or length > BUNDLE_MAX_LENGTH
            ):
                # perdemos o enquadramento: descarta 1 byte e ressincroniza
                del buf[:1]
                self._synced = False
                continue

            if len(buf) < length:
                return  # espera o resto do bundle

            body = bytes(buf[BUNDLE_HEADER_SIZE:length])
            del buf[:length]
            # otimista: os próximos bytes devem ser outro bundle; se o header
            # seguinte falhar na validação, ressincronizamos acima.
            yield header, body


def decode_body(header: XivBundleHeader, body: bytes) -> Optional[bytes]:
    """Descomprime o corpo do bundle. Devolve None para Oodle (Fase 3)."""
    comp = header.compression
    if comp == Compression.NONE:
        return body
    if comp == Compression.ZLIB:
        try:
            return zlib.decompress(body)
        except zlib.error:
            try:
                return zlib.decompress(body, -zlib.MAX_WBITS)  # raw deflate
            except zlib.error:
                return None
    return None  # Oodle (2) ainda não suportado


def iter_messages(
    header: XivBundleHeader, decoded_body: bytes
) -> Iterator[Tuple[XivMessageHeader, bytes]]:
    off = 0
    n = len(decoded_body)
    for _ in range(header.message_count):
        if off + MESSAGE_HEADER_SIZE > n:
            break
        msg = XivMessageHeader.from_buffer_copy(
            decoded_body[off : off + MESSAGE_HEADER_SIZE]
        )
        if msg.length < MESSAGE_HEADER_SIZE or off + msg.length > n:
            break
        payload = decoded_body[off + MESSAGE_HEADER_SIZE : off + msg.length]
        yield msg, payload
        off += msg.length


def read_opcode(msg: XivMessageHeader, payload: bytes) -> Optional[int]:
    if msg.type_int != int(XivMessageType.Ipc):
        return None
    if len(payload) < IPC_HEADER_SIZE:
        return None
    ipc = XivMessageIpcHeader.from_buffer_copy(payload[:IPC_HEADER_SIZE])
    if ipc.type_int != 0x0014:  # só mensagens IPC de jogo "interessantes"
        return None
    return ipc.subtype  # o opcode real é o subtype, não o type_int
