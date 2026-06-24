import ctypes
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.mitigation.mitigator import Mitigator
from mitigus.protocol.headers import (
    BUNDLE_HEADER_SIZE,
    BUNDLE_MAGIC,
    IPC_HEADER_SIZE,
    MESSAGE_HEADER_SIZE,
    XivBundleHeader,
    XivMessageHeader,
    XivMessageIpcHeader,
)
from mitigus.protocol.ipc import (
    XivMessageIpcActionEffect,
    XivMessageIpcActionRequestCommon,
    XivMessageIpcActorCast,
    XivMessageIpcCustomOriginalWaitTime,
    XivMitmLatencyMitigatorCustomSubtype,
)
from mitigus.protocol.opcodes import OpcodeDefinition

OPCODES = OpcodeDefinition.from_dict(
    {
        "Name": "test",
        "C2S_ActionRequest": "0x0123",
        "C2S_ActionRequestGroundTargeted": "0x0124",
        "S2C_ActionEffect01": "0x0201",
        "S2C_ActionEffect08": "0x0208",
        "S2C_ActionEffect16": "0x0216",
        "S2C_ActionEffect24": "0x0224",
        "S2C_ActionEffect32": "0x0232",
        "S2C_ActorCast": "0x0301",
        "S2C_ActorControl": "0x0302",
        "S2C_ActorControlSelf": "0x0303",
        "Common_UseOodleTcp": False,
        "Server_IpRange": "",
        "Server_PortRange": "",
    }
)


def ipc_message(subtype, payload, source_actor=1, target_actor=1, type_int=0x0014):
    ipc = XivMessageIpcHeader()
    ipc.type_int = type_int
    ipc.subtype = subtype
    data = bytes(ipc) + bytes(payload)
    mh = XivMessageHeader()
    mh.source_actor = source_actor
    mh.target_actor = target_actor
    mh.type_int = 3  # Ipc
    mh.length = MESSAGE_HEADER_SIZE + len(data)
    return bytes(mh) + data


def bundle(messages, conn_type=1):
    body = b"".join(messages)
    h = XivBundleHeader()
    h.magic[:] = list(BUNDLE_MAGIC)
    h.timestamp = 0
    h.conn_type = conn_type
    h.message_count = len(messages)
    h.compression = 0
    h.decoded_body_length = len(body)
    h.length = BUNDLE_HEADER_SIZE + len(body)
    return bytes(h) + body


def parse(data):
    h = XivBundleHeader.from_buffer_copy(data[:BUNDLE_HEADER_SIZE])
    body = data[BUNDLE_HEADER_SIZE : h.length]
    msgs, off = [], 0
    for _ in range(h.message_count):
        mh = XivMessageHeader.from_buffer_copy(body[off : off + MESSAGE_HEADER_SIZE])
        md = body[off + MESSAGE_HEADER_SIZE : off + mh.length]
        msgs.append((mh, md))
        off += mh.length
    return h, msgs


def find_ipc(msgs, subtype, type_int=0x0014):
    for mh, md in msgs:
        ipc = XivMessageIpcHeader.from_buffer_copy(md[:IPC_HEADER_SIZE])
        if ipc.type_int == type_int and ipc.subtype == subtype:
            return mh, md
    return None


def read_effect(md):
    return XivMessageIpcActionEffect.from_buffer_copy(
        md[IPC_HEADER_SIZE : IPC_HEADER_SIZE + ctypes.sizeof(XivMessageIpcActionEffect)]
    )


class MitigationTest(unittest.TestCase):
    def test_instant_action_lock_reduced_and_original_preserved(self):
        clock = [100.0]
        m = Mitigator(OPCODES, oodle=None, extra_delay=0.075, clock=lambda: clock[0])

        req = XivMessageIpcActionRequestCommon(action_id=0x1D, sequence=5)
        m.c2s(bundle([ipc_message(OPCODES.C2S_ActionRequest, req)]))
        self.assertEqual(len(m.pending_actions), 1)

        clock[0] = 100.5  # RTT de 0.5s
        eff = XivMessageIpcActionEffect()
        eff.action_id = 0x1D
        eff.source_sequence = 5
        eff.animation_lock_duration = 0.6
        out = m.s2c(bundle([ipc_message(OPCODES.S2C_ActionEffect01, eff)]))

        h, msgs = parse(out)
        self.assertEqual(h.message_count, 2)  # effect + custom OriginalWaitTime inserido

        eff_out = read_effect(find_ipc(msgs, OPCODES.S2C_ActionEffect01)[1])
        # 100.0 + 0.6 + 0.075 - 100.5 = 0.175
        self.assertAlmostEqual(eff_out.animation_lock_duration, 0.175, places=3)

        custom = find_ipc(msgs, int(XivMitmLatencyMitigatorCustomSubtype.OriginalWaitTime), type_int=0xE852)
        self.assertIsNotNone(custom)
        owt = XivMessageIpcCustomOriginalWaitTime.from_buffer_copy(
            custom[1][IPC_HEADER_SIZE : IPC_HEADER_SIZE + ctypes.sizeof(XivMessageIpcCustomOriginalWaitTime)]
        )
        self.assertEqual(owt.source_sequence, 5)
        self.assertAlmostEqual(owt.original_wait_time, 0.6, places=3)
        self.assertEqual(len(m.pending_actions), 0)

    def test_passthrough_unmodified_bundle_is_identical(self):
        m = Mitigator(OPCODES, oodle=None, clock=lambda: 0.0)
        inp = bundle([ipc_message(0x09AB, b"\x01\x02\x03\x04")])  # opcode irrelevante
        out = m.s2c(inp)
        self.assertEqual(out, inp)

    def test_cast_action_is_not_adjusted(self):
        clock = [200.0]
        m = Mitigator(OPCODES, oodle=None, clock=lambda: clock[0])

        req = XivMessageIpcActionRequestCommon(action_id=0x2A, sequence=9)
        m.c2s(bundle([ipc_message(OPCODES.C2S_ActionRequest, req)]))

        cast = XivMessageIpcActorCast()
        cast.action_id = 0x2A
        m.s2c(bundle([ipc_message(OPCODES.S2C_ActorCast, cast)]))
        self.assertTrue(m.pending_actions[0].is_cast)

        clock[0] = 201.0
        eff = XivMessageIpcActionEffect()
        eff.action_id = 0x2A
        eff.source_sequence = 9
        eff.animation_lock_duration = 0.5
        out = m.s2c(bundle([ipc_message(OPCODES.S2C_ActionEffect01, eff)]))

        h, msgs = parse(out)
        self.assertEqual(h.message_count, 1)  # cast não é ajustado -> nada inserido
        eff_out = read_effect(find_ipc(msgs, OPCODES.S2C_ActionEffect01)[1])
        self.assertAlmostEqual(eff_out.animation_lock_duration, 0.5, places=3)

    def test_disabled_hub_does_not_modify_but_records_telemetry(self):
        from mitigus.panel.hub import ControlHub

        hub = ControlHub(enabled=False)
        clock = [100.0]
        m = Mitigator(OPCODES, oodle=None, clock=lambda: clock[0], hub=hub)

        req = XivMessageIpcActionRequestCommon(action_id=0x1D, sequence=5)
        m.c2s(bundle([ipc_message(OPCODES.C2S_ActionRequest, req)]))
        clock[0] = 100.5
        eff = XivMessageIpcActionEffect()
        eff.action_id = 0x1D
        eff.source_sequence = 5
        eff.animation_lock_duration = 0.6
        out = m.s2c(bundle([ipc_message(OPCODES.S2C_ActionEffect01, eff)]))

        h, msgs = parse(out)
        self.assertEqual(h.message_count, 1)  # desligado -> sem rewrite/custom
        eff_out = read_effect(find_ipc(msgs, OPCODES.S2C_ActionEffect01)[1])
        self.assertAlmostEqual(eff_out.animation_lock_duration, 0.6, places=3)

        tele = hub.status()["telemetry"]
        self.assertEqual(tele["total_actions"], 1)  # telemetria ainda registra
        self.assertEqual(tele["last_saved_ms"], 0)  # mas economia 0 (desligado)
        self.assertEqual(tele["last_rtt_ms"], 500)

    def test_partial_bundle_is_buffered(self):
        m = Mitigator(OPCODES, oodle=None, clock=lambda: 0.0)
        full = bundle([ipc_message(0x09AB, b"\x01\x02\x03\x04")])
        half = full[: len(full) // 2]
        self.assertEqual(m.s2c(half), b"")  # incompleto -> nada emitido ainda
        rest = m.s2c(full[len(full) // 2 :])
        self.assertEqual(rest, full)  # completa e re-serializa


_NEW_OPCODES = OpcodeDefinition.from_dict({
    "Name": "novo", "C2S_ActionRequest": "0x0999", "C2S_ActionRequestGroundTargeted": "0x0998",
    "S2C_ActionEffect01": "0x0501", "S2C_ActionEffect08": "0x0508", "S2C_ActionEffect16": "0x0516",
    "S2C_ActionEffect24": "0x0524", "S2C_ActionEffect32": "0x0532", "S2C_ActorCast": "0x0601",
    "S2C_ActorControl": "0x0602", "S2C_ActorControlSelf": "0x0603", "Common_UseOodleTcp": True,
    "Server_IpRange": "", "Server_PortRange": "",
})


class OpcodeWatchdogTest(unittest.TestCase):
    def _hub(self):
        from mitigus.panel.hub import ControlHub
        return ControlHub(clock=lambda: 0.0)

    def test_recognized_combat_is_counted(self):
        hub = self._hub()
        m = Mitigator(OPCODES, oodle=None, clock=lambda: 0.0, hub=hub)
        m.s2c(bundle([ipc_message(OPCODES.S2C_ActorCast, b"\x00" * 32)]))
        self.assertEqual(hub.take_opcode_window(), (1, 1))   # interessada e reconhecida

    def test_stale_opcodes_interested_but_unrecognized(self):
        # opcodes velhos: 60 mensagens "interessantes" (0x0014) com subtype que não casa
        hub = self._hub()
        m = Mitigator(OPCODES, oodle=None, clock=lambda: 0.0, hub=hub)
        m.s2c(bundle([ipc_message(0x09AB, b"\x00" * 32) for _ in range(60)]))
        interested, recognized = hub.take_opcode_window()
        self.assertEqual((interested, recognized), (60, 0))
        self.assertTrue(interested >= 50 and recognized == 0)  # gatilho do watchdog

    def test_take_opcode_window_resets(self):
        hub = self._hub()
        hub.note_opcodes(10, 3)
        hub.note_opcodes(5, 0)
        self.assertEqual(hub.take_opcode_window(), (15, 3))
        self.assertEqual(hub.take_opcode_window(), (0, 0))     # janela zerou

    def test_reload_opcodes_swaps_live(self):
        m = Mitigator(OPCODES, oodle=None, clock=lambda: 0.0)
        self.assertTrue(m.opcodes.is_action_effect(0x0201))    # opcode antigo casa
        m.reload_opcodes(_NEW_OPCODES)
        self.assertFalse(m.opcodes.is_action_effect(0x0201))   # antigo não casa mais
        self.assertTrue(m.opcodes.is_action_effect(0x0501))    # novo casa
        self.assertTrue(m._use_oodle_tcp)                      # flag atualizado junto


if __name__ == "__main__":
    unittest.main()
