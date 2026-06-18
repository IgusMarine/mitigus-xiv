import ctypes
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.capture.recorder import SegmentRecorder
from mitigus.mitigation.mitigator import Mitigator
from mitigus.protocol.headers import (
    BUNDLE_HEADER_SIZE,
    BUNDLE_MAGIC,
    MESSAGE_HEADER_SIZE,
    XivBundleHeader,
    XivMessageHeader,
    XivMessageIpcHeader,
    XivMessageType,
)
from mitigus.protocol.opcodes import OpcodeDefinition


def make_ipc_message(opcode, ipc_type=0x0014, src=0x1111, tgt=0x1111, body=b"\xAB" * 8):
    ipc = XivMessageIpcHeader()
    ipc.type_int = ipc_type
    ipc.subtype = opcode
    md = bytes(ipc) + body
    mh = XivMessageHeader()
    mh.length = MESSAGE_HEADER_SIZE + len(md)
    mh.source_actor = src
    mh.target_actor = tgt
    mh.type_int = int(XivMessageType.Ipc)
    return bytes(mh) + md, mh, bytearray(md)


def make_bundle(message_blobs):
    body = b"".join(message_blobs)
    h = XivBundleHeader()
    h.magic = (ctypes.c_ubyte * 16)(*BUNDLE_MAGIC)
    h.timestamp = 1234567890
    h.conn_type = 1
    h.message_count = len(message_blobs)
    h.encoding = 0
    h.compression = 0  # none -> não precisa de Oodle
    h.decoded_body_length = len(body)
    h.length = BUNDLE_HEADER_SIZE + len(body)
    return bytes(h) + body, h


def _dummy_opcodes():
    # valores que NÃO colidem com os opcodes de teste (0x1234, 0x01D0)
    data = {"Name": "test", "Common_UseOodleTcp": False}
    for i, f in enumerate((
        "C2S_ActionRequest", "C2S_ActionRequestGroundTargeted",
        "S2C_ActionEffect01", "S2C_ActionEffect08", "S2C_ActionEffect16",
        "S2C_ActionEffect24", "S2C_ActionEffect32",
        "S2C_ActorCast", "S2C_ActorControl", "S2C_ActorControlSelf",
    ), start=1):
        data[f] = i
    return OpcodeDefinition.from_dict(data)


def _read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "cap.jsonl")

    def test_records_ipc_segments(self):
        blob, mh, md = make_ipc_message(0x1234)
        _, header = make_bundle([blob])
        rec = SegmentRecorder(self.path)
        rec.record_bundle("s2c", header, [[mh, md]])
        rec.close()

        rows = _read_jsonl(self.path)
        self.assertEqual(rows[0]["_meta"], "mitigus-capture")
        seg = rows[1]
        self.assertEqual(seg["dir"], "s2c")
        self.assertEqual(seg["op"], 0x1234)
        self.assertEqual(seg["itype"], 0x0014)
        self.assertEqual(seg["ts"], 1234567890)
        # payload gravado = bytes pristine começando no header IPC (opcode em off2)
        self.assertEqual(bytes.fromhex(seg["data"]), bytes(md))
        self.assertEqual(int.from_bytes(bytes.fromhex(seg["data"])[2:4], "little"), 0x1234)
        self.assertEqual(rows[-1]["_meta"], "end")
        self.assertEqual(rows[-1]["segments"], 1)


class MitigatorCaptureSeamTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "cap.jsonl")

    def test_capture_is_pristine_and_passthrough(self):
        # msg1 = "interessante" (0x0014); msg2 = marca diferente (como o pacote
        # inicializador de ofuscação) que os handlers IGNORAM mas a captura PEGA.
        m1, _, _ = make_ipc_message(0x1234, ipc_type=0x0014)
        m2, _, _ = make_ipc_message(0x01D0, ipc_type=0x00AA)
        bundle, _ = make_bundle([m1, m2])

        rec = SegmentRecorder(self.path)
        mit = Mitigator(_dummy_opcodes(), oodle=None, capture=rec)
        out = mit.s2c(bundle)
        rec.close()

        # tráfego sai intacto (compression=0, nada casou os opcodes)
        self.assertEqual(out, bundle)

        rows = [r for r in _read_jsonl(self.path) if "op" in r]
        self.assertEqual(len(rows), 2)
        ops = {r["op"]: r["itype"] for r in rows}
        self.assertEqual(ops[0x1234], 0x0014)
        self.assertEqual(ops[0x01D0], 0x00AA)  # o "inicializador" foi capturado

    def test_no_capture_is_inert(self):
        m1, _, _ = make_ipc_message(0x1234)
        bundle, _ = make_bundle([m1])
        mit = Mitigator(_dummy_opcodes(), oodle=None)  # capture=None
        self.assertEqual(mit.s2c(bundle), bundle)


if __name__ == "__main__":
    unittest.main()
