"""
Gravador de segmentos IPC pós-Oodle (variante DPS / branch dps-meter).

Recebe do Mitigator (via o sink `capture`) os bundles JÁ decodificados e grava
cada segmento num arquivo JSONL — um objeto por linha. É o material bruto para
desofuscar/analisar offline (alimentar `research/deob`).

Os bytes gravados são PRISTINE (capturados antes da mitigação reescrever
qualquer campo), então `data` é exatamente o que o console recebeu no fio:
começa no HEADER IPC, com o opcode (subtype) em offset 2 — o formato que o
desofuscador espera.

100% read-only sobre o tráfego: nunca altera `messages`. Roda no loop asyncio
(thread única), então não precisa de lock. Qualquer erro de I/O é engolido para
não derrubar o relay.

Formato (JSONL):
  linha 1: {"_meta":"mitigus-capture","v":1,"started": <epoch_ms_local>}
  demais : {"dir","ts","conn","comp","mtype","src","tgt","itype","op","len","data"}
    dir   c2s|s2c     ts    timestamp do bundle (ms, do fio)
    conn  1=zone/2=chat   comp 0/1/2 (compressão original do bundle)
    mtype tipo do segmento (3=Ipc)   src/tgt source/target actor
    itype marca IPC (0x0014 etc.)    op   opcode real (subtype, offset 2)
    len   tamanho do payload IPC     data hex do payload (do header IPC em diante)
"""
from __future__ import annotations

import json

from ..protocol.headers import (
    IPC_HEADER_SIZE,
    XivMessageIpcHeader,
    XivMessageType,
)

_IPC = int(XivMessageType.Ipc)  # 3


class SegmentRecorder:
    def __init__(self, path: str, ipc_only: bool = True, started_ms: int = 0):
        self.path = path
        self._ipc_only = ipc_only
        self._fh = open(path, "w", encoding="utf-8", buffering=1)
        self.count = 0
        self.bundles = 0
        self._fh.write(json.dumps(
            {"_meta": "mitigus-capture", "v": 1, "started": int(started_ms)}
        ) + "\n")

    # Pode ser passado direto como o sink `capture` do Mitigator.
    def __call__(self, direction, header, messages) -> None:
        self.record_bundle(direction, header, messages)

    def record_bundle(self, direction, header, messages) -> None:
        self.bundles += 1
        for mh, md in messages:
            is_ipc = mh.type_int == _IPC
            if self._ipc_only and not is_ipc:
                continue
            rec = {
                "dir": direction,
                "ts": int(header.timestamp),
                "conn": int(header.conn_type),
                "comp": int(header.compression),
                "mtype": int(mh.type_int),
                "src": int(mh.source_actor),
                "tgt": int(mh.target_actor),
            }
            if is_ipc and len(md) >= IPC_HEADER_SIZE:
                ipc = XivMessageIpcHeader.from_buffer_copy(bytes(md[:IPC_HEADER_SIZE]))
                rec["itype"] = int(ipc.type_int)
                rec["op"] = int(ipc.subtype)
            rec["len"] = len(md)
            rec["data"] = bytes(md).hex()
            try:
                self._fh.write(json.dumps(rec) + "\n")
                self.count += 1
            except Exception:
                pass

    def close(self) -> None:
        try:
            self._fh.write(json.dumps(
                {"_meta": "end", "bundles": self.bundles, "segments": self.count}
            ) + "\n")
            self._fh.close()
        except Exception:
            pass
