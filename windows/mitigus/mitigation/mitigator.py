"""
Mitigador por conexão (Fase 4) — port fiel do `mitigate.py`.

Junta tudo: para cada bundle completo de uma direção, decodifica (zlib/none/Oodle
por canal), processa as mensagens IPC e re-serializa/re-comprime. A mitigação em si
está em `_to_downstream`: casa o `ActionEffect` (servidor->cliente) com o
`ActionRequest` (cliente->servidor) por `sequence`, mede o tempo decorrido e
reescreve o `animation_lock_duration` — subtraindo o RTT já transcorrido e somando
a margem `extra_delay` (0.075). Isso restaura o double-weave em ping alto.

Implementa o protocolo `Processor` (métodos `c2s`/`s2c`) que entra nos hooks do
relay. Estado por conexão; roda inteiro no loop asyncio (sem threads), então não
precisa de lock. O `clock` é injetável para testes determinísticos.

Canais Oodle (como o original): C2S decode=0/encode=1; S2C decode=2/encode=3.
Quando a definição não usa Oodle TCP, ambos usam o canal UDP (0xFFFFFFFF).
"""
from __future__ import annotations

import ctypes
import math
import time
import zlib
from collections import deque
from typing import Callable, List, Optional, Tuple

from ..protocol.headers import (
    BUNDLE_HEADER_SIZE,
    BUNDLE_MAGIC,
    BUNDLE_MAGIC_ZERO,
    BUNDLE_MAX_LENGTH,
    IPC_HEADER_SIZE,
    MESSAGE_HEADER_SIZE,
    XivBundleHeader,
    XivMessageHeader,
    XivMessageIpcHeader,
    XivMessageIpcType,
    XivMessageType,
)
from ..protocol.ipc import (
    AUTO_ATTACK_DELAY,
    DEFAULT_EXTRA_DELAY,
    XivMessageIpcActionEffect,
    XivMessageIpcActionRequestCommon,
    XivMessageIpcActorCast,
    XivMessageIpcActorControl,
    XivMessageIpcActorControlCategory,
    XivMessageIpcActorControlSelf,
    XivMessageIpcCustomOriginalWaitTime,
    XivMitmLatencyMitigatorCustomSubtype,
)
from ..protocol.opcodes import OpcodeDefinition
from .stats import NumericStatisticsTracker, PendingAction

UDP_CHANNEL = 0xFFFFFFFF

# Item retornado por _parse: ("raw", bytes) ou ("bundle", header, messages)
_Message = List  # [XivMessageHeader, bytearray]


class Mitigator:
    def __init__(
        self,
        opcodes: OpcodeDefinition,
        oodle=None,
        extra_delay: float = DEFAULT_EXTRA_DELAY,
        measure_ping: bool = False,
        insert_original_wait_time: bool = True,
        clock: Callable[[], float] = time.time,
        on_log: Optional[Callable[[str], None]] = None,
        hub=None,
        adaptive: bool = True,
        adaptive_k: float = 1.0,
        adaptive_max: float = 0.20,
        capture=None,
    ):
        self.opcodes = opcodes
        self.oodle = oodle
        self.extra_delay = extra_delay
        self.measure_ping = measure_ping
        # margem adaptativa: a margem de segurança cresce com o JITTER do rtt.
        # Linha estável -> margem ~= base (corte mais agressivo). Linha instável ->
        # margem maior (não corta demais, evita rubberband). Nunca abaixo da base.
        self.adaptive = adaptive
        self.adaptive_k = adaptive_k        # quantos desvios-padrão somar à base
        self.adaptive_max = adaptive_max    # teto da margem (s)
        self.insert_original_wait_time = insert_original_wait_time
        self._clock = clock
        self._log = on_log or (lambda m: None)
        self._hub = hub  # ControlHub opcional: liga/desliga em runtime + telemetria
        self._use_oodle_tcp = bool(opcodes.Common_UseOodleTcp)
        # Modo de inspeção (run_tap.py): decodifica + detecta + loga o corte, mas NÃO
        # reserializa/reencoda (read-only). Produção deixa False.
        self.dry_run = False
        # Sink de captura opcional (variante DPS): callable(direction, header,
        # messages). Recebe os segmentos PRISTINE pós-Oodle (antes do process_fn),
        # ou seja, os bytes exatos do fio — material para desofuscação offline.
        # None em produção: caminho idêntico ao atual (só um if a mais).
        self._capture = capture

        self.pending_actions: deque = deque()
        self.last_animation_lock_ends_at = 0.0
        self.last_successful_request = PendingAction(0, 0)
        self.latency_application = NumericStatisticsTracker(10)
        self.latency_exaggeration = NumericStatisticsTracker(10, 30.0)

        self._c2s_buf = bytearray()
        self._s2c_buf = bytearray()

    def _enabled(self) -> bool:
        return self._hub.is_enabled() if self._hub is not None else True

    # ---- protocolo Processor (entra nos hooks do relay) ------------------
    def c2s(self, data: bytes) -> bytes:
        return self._process(self._c2s_buf, data, 0, 1, self._to_upstream)

    def s2c(self, data: bytes) -> bytes:
        return self._process(self._s2c_buf, data, 2, 3, self._to_downstream)

    # ---- pipeline por direção --------------------------------------------
    def _process(self, buf: bytearray, data: bytes, decode_ch: int, encode_ch: int, process_fn) -> bytes:
        if data:
            buf.extend(data)
        out = bytearray()
        items, consumed = self._parse(buf, decode_ch)
        for item in items:
            if item[0] == "raw":
                if not self.dry_run:
                    out.extend(item[1])
            else:
                _, header, messages = item
                if self._capture is not None:
                    # PRISTINE: antes de process_fn (que pode reescrever campos).
                    # read-only; uma falha de captura nunca derruba o relay.
                    direction = "c2s" if decode_ch == 0 else "s2c"
                    try:
                        self._capture(direction, header, messages)
                    except Exception:
                        pass
                process_fn(header, messages)  # detecta + loga o corte (sempre)
                if not self.dry_run:
                    out.extend(self._serialize(header, messages, encode_ch))
        if consumed:
            del buf[:consumed]
        return bytes(out)

    def _parse(self, data: bytearray, decode_ch: int) -> Tuple[list, int]:
        items: list = []
        offset = 0
        n = len(data)
        m1, m2 = BUNDLE_MAGIC, BUNDLE_MAGIC_ZERO
        while offset < n:
            avail = n - offset
            if avail >= len(m1):
                mc1, mc2 = data.find(m1, offset), data.find(m2, offset)
            else:
                mc1, mc2 = data.find(m1[:avail], offset), data.find(m2[:avail], offset)
            if mc1 == -1:
                i = mc2
            elif mc2 == -1:
                i = mc1
            else:
                i = min(mc1, mc2)

            if i == -1:
                items.append(("raw", bytes(data[offset:])))
                offset = n
                break
            if i != offset:
                items.append(("raw", bytes(data[offset:i])))
                offset = i

            if n - offset < BUNDLE_HEADER_SIZE:
                break
            header = XivBundleHeader.from_buffer_copy(bytes(data[offset : offset + BUNDLE_HEADER_SIZE]))
            length = header.length
            if length < BUNDLE_HEADER_SIZE or length > BUNDLE_MAX_LENGTH:
                items.append(("raw", bytes(data[offset : offset + 1])))
                offset += 1
                continue
            if n - offset < length:
                break  # bundle incompleto

            body = bytes(data[offset + BUNDLE_HEADER_SIZE : offset + length])
            try:
                decoded = self._decode_body(header.compression, body, header.decoded_body_length, decode_ch)
                messages = self._split_messages(header, decoded)
            except Exception:
                items.append(("raw", bytes(data[offset : offset + 1])))
                offset += 1
                continue
            offset += length
            items.append(("bundle", header, messages))
        return items, offset

    def _split_messages(self, header: XivBundleHeader, decoded: bytearray) -> List[_Message]:
        messages: List[_Message] = []
        off = 0
        n = len(decoded)
        for _ in range(header.message_count):
            if off + MESSAGE_HEADER_SIZE > n:
                raise ValueError("mensagem truncada")
            mh = XivMessageHeader.from_buffer_copy(bytes(decoded[off : off + MESSAGE_HEADER_SIZE]))
            if mh.length < MESSAGE_HEADER_SIZE or off + mh.length > n:
                raise ValueError("comprimento de mensagem inválido")
            md = bytearray(decoded[off + MESSAGE_HEADER_SIZE : off + mh.length])
            messages.append([mh, md])
            off += mh.length
        return messages

    def _serialize(self, header: XivBundleHeader, messages: List[_Message], encode_ch: int) -> bytes:
        body = bytearray()
        for mh, md in messages:
            body.extend(bytes(mh))
            body.extend(md)
        header.decoded_body_length = len(body)
        header.message_count = len(messages)

        comp = header.compression
        if comp == 1:
            out_body = zlib.compress(bytes(body))
        elif comp == 2:
            ch = encode_ch if self._use_oodle_tcp else UDP_CHANNEL
            out_body = self.oodle.encode(ch, bytes(body))
        else:
            out_body = bytes(body)
        header.length = BUNDLE_HEADER_SIZE + len(out_body)
        return bytes(header) + out_body

    def _decode_body(self, compression: int, body: bytes, decoded_len: int, tcp_channel: int) -> bytearray:
        if compression == 0:
            return bytearray(body)
        if compression == 1:
            return bytearray(zlib.decompress(body))
        if compression == 2:
            if self.oodle is None:
                raise RuntimeError("bundle Oodle, mas o codec não está carregado (Fase 3)")
            ch = tcp_channel if self._use_oodle_tcp else UDP_CHANNEL
            return bytearray(self.oodle.decode(ch, body, decoded_len))
        raise RuntimeError(f"compressão não suportada: {compression}")

    # ---- lógica de mitigação ---------------------------------------------
    def _to_upstream(self, bundle_header: XivBundleHeader, messages: List[_Message]) -> None:
        for mh, md in messages:
            if mh.type != XivMessageType.Ipc or len(md) < IPC_HEADER_SIZE:
                continue
            try:
                ipc = XivMessageIpcHeader.from_buffer(md)
                if ipc.type != XivMessageIpcType.UnknownButInterested:
                    continue
                if ipc.subtype not in (
                    self.opcodes.C2S_ActionRequest,
                    self.opcodes.C2S_ActionRequestGroundTargeted,
                ):
                    continue
                request = XivMessageIpcActionRequestCommon.from_buffer(md, IPC_HEADER_SIZE)
                pa = PendingAction(request.action_id, request.sequence, request_timestamp=self._clock())
                self.pending_actions.append(pa)
                if pa.request_timestamp > self.last_animation_lock_ends_at and len(self.pending_actions) == 1:
                    self.last_animation_lock_ends_at = pa.request_timestamp
                self._log(f"C2S_ActionRequest actionId={request.action_id:04x} sequence={request.sequence:04x}")
            except Exception:
                continue

    def _to_downstream(self, bundle_header: XivBundleHeader, messages: List[_Message]) -> None:
        insertions: List[Tuple[int, _Message]] = []
        wait_time_dict: dict = {}
        for i, (mh, md) in enumerate(messages):
            if mh.type != XivMessageType.Ipc or mh.source_actor != mh.target_actor or len(md) < IPC_HEADER_SIZE:
                continue
            try:
                ipc = XivMessageIpcHeader.from_buffer(md)
                if (
                    ipc.type == XivMessageIpcType.XivMitmLatencyMitigatorCustom
                    and ipc.subtype == int(XivMitmLatencyMitigatorCustomSubtype.OriginalWaitTime)
                ):
                    owt = XivMessageIpcCustomOriginalWaitTime.from_buffer(md, IPC_HEADER_SIZE)
                    wait_time_dict[owt.source_sequence] = owt.original_wait_time
                if ipc.type != XivMessageIpcType.UnknownButInterested:
                    continue

                if self.opcodes.is_action_effect(ipc.subtype):
                    self._handle_action_effect(i, mh, md, ipc, wait_time_dict, insertions)
                elif ipc.subtype == self.opcodes.S2C_ActorControlSelf:
                    self._handle_rollback(md)
                elif ipc.subtype == self.opcodes.S2C_ActorControl:
                    self._handle_cancel_cast(md)
                elif ipc.subtype == self.opcodes.S2C_ActorCast:
                    if self.pending_actions:
                        self.pending_actions[0].is_cast = True
            except Exception:
                continue

        for i, entry in reversed(insertions):
            messages.insert(i, entry)

    def _handle_action_effect(self, index, mh, md, ipc, wait_time_dict, insertions) -> None:
        effect = XivMessageIpcActionEffect.from_buffer(md, IPC_HEADER_SIZE)
        original_wait_time = wait_time_dict.get(effect.source_sequence, effect.animation_lock_duration)
        wait_time = original_wait_time
        now = self._clock()
        extra = ""

        if effect.source_sequence == 0:
            # ação originada no servidor
            if (
                not self.last_successful_request.is_cast
                and self.last_successful_request.sequence
                and self.last_animation_lock_ends_at > now
            ):
                self.last_successful_request.action_id = effect.action_id
                self.last_successful_request.sequence = 0
                self.last_animation_lock_ends_at += (original_wait_time + now) - (
                    self.last_successful_request.original_wait_time
                    + self.last_successful_request.response_timestamp
                )
                self.last_animation_lock_ends_at = max(self.last_animation_lock_ends_at, now + AUTO_ATTACK_DELAY)
                wait_time = self.last_animation_lock_ends_at - now
            extra += " serverOriginated"
        else:
            while self.pending_actions and self.pending_actions[0].sequence != effect.source_sequence:
                self.pending_actions.popleft()
            if self.pending_actions:
                self.last_successful_request = self.pending_actions.popleft()
                self.last_successful_request.response_timestamp = now
                self.last_successful_request.original_wait_time = original_wait_time
                if not self.last_successful_request.is_cast:
                    rtt = (
                        self.last_successful_request.response_timestamp
                        - self.last_successful_request.request_timestamp
                    )
                    self.latency_application.add(rtt)
                    extra += f" rtt={rtt * 1000:.0f}ms"
                    if self._enabled():
                        delay, msg_append = self.resolve_adjusted_extra_delay(rtt)
                        extra += msg_append
                        self.last_animation_lock_ends_at += original_wait_time + delay
                        wait_time = self.last_animation_lock_ends_at - now
                    if self._hub is not None:
                        self._hub.record_effect(original_wait_time * 1000, wait_time * 1000, rtt * 1000)

        if math.isclose(wait_time, original_wait_time):
            self._log(
                f"S2C_ActionEffect actionId={effect.action_id:04x} seq={effect.source_sequence:04x} "
                f"wait={int(original_wait_time * 1000)}ms{extra}"
            )
            return

        self._log(
            f"S2C_ActionEffect actionId={effect.action_id:04x} seq={effect.source_sequence:04x} "
            f"wait={int(original_wait_time * 1000)}ms->{int(wait_time * 1000)}ms{extra}"
        )
        effect.animation_lock_duration = max(0.0, wait_time)

        if self.insert_original_wait_time:
            insertions.append((index, self._build_original_wait_time(mh, ipc, effect, original_wait_time)))

    def _build_original_wait_time(self, mh, ipc, effect, original_wait_time) -> _Message:
        custom_md = bytearray(ctypes.sizeof(XivMessageIpcCustomOriginalWaitTime) + IPC_HEADER_SIZE)
        custom_ipc = XivMessageIpcHeader.from_buffer(custom_md)
        custom_ipc.type = XivMessageIpcType.XivMitmLatencyMitigatorCustom
        custom_ipc.subtype = int(XivMitmLatencyMitigatorCustomSubtype.OriginalWaitTime)
        custom_ipc.server_id = ipc.server_id
        custom_ipc.epoch = ipc.epoch
        owt = XivMessageIpcCustomOriginalWaitTime.from_buffer(custom_md, IPC_HEADER_SIZE)
        owt.source_sequence = effect.source_sequence
        owt.original_wait_time = original_wait_time  # (o original deixava em 0; aqui preenchemos)

        custom_mh = XivMessageHeader()
        custom_mh.source_actor = mh.source_actor
        custom_mh.target_actor = mh.target_actor
        custom_mh.type = XivMessageType.Ipc
        custom_mh.length = MESSAGE_HEADER_SIZE + len(custom_md)
        return [custom_mh, custom_md]

    def _handle_rollback(self, md) -> None:
        control = XivMessageIpcActorControlSelf.from_buffer(md, IPC_HEADER_SIZE)
        if control.category != XivMessageIpcActorControlCategory.Rollback:
            return
        action_id = control.param_3
        source_sequence = control.param_6
        while self.pending_actions and (
            (source_sequence and self.pending_actions[0].sequence != source_sequence)
            or (not source_sequence and self.pending_actions[0].action_id != action_id)
        ):
            self.pending_actions.popleft()
        if self.pending_actions:
            self.pending_actions.popleft()
        self._log(f"S2C_ActorControlSelf/Rollback actionId={action_id:04x} seq={source_sequence:08x}")

    def _handle_cancel_cast(self, md) -> None:
        control = XivMessageIpcActorControl.from_buffer(md, IPC_HEADER_SIZE)
        if control.category != XivMessageIpcActorControlCategory.CancelCast:
            return
        action_id = control.param_3
        while self.pending_actions and self.pending_actions[0].action_id != action_id:
            self.pending_actions.popleft()
        if self.pending_actions:
            self.pending_actions.popleft()
        self._log(f"S2C_ActorControl/CancelCast actionId={action_id:04x}")

    def resolve_adjusted_extra_delay(self, rtt: float) -> Tuple[float, str]:
        # A margem base vem do hub (ajustável ao vivo pelo painel) ou do valor fixo.
        # Com adaptive ligado, somamos k*jitter (desvio dos rtt recentes), com teto:
        # quanto mais instável a linha, maior a margem de segurança — é o que faz o
        # weave parar de falhar em ping alto e com jitter (estilo NoClippy).
        base = self._hub.extra_delay() if self._hub is not None else self.extra_delay
        if not self.adaptive:
            return base, ""
        dev = self.latency_application.deviation() or 0.0  # o rtt atual já foi add()
        margin = min(self.adaptive_max, max(base, base + self.adaptive_k * dev))
        return margin, f" jitter={dev * 1000:.0f}ms margin={margin * 1000:.0f}ms"
