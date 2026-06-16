"""
Teste end-to-end do pipeline offline: formato de captura -> derivação de chave
do inicializador -> descramble -> parse do ActionEffect.

Monta uma captura SINTÉTICA (inicializador + um ActionEffect embaralhado com as
chaves derivadas dele) e roda o replay. Prova que toda a cadeia casa. O que
continua pendente é só: bytes REAIS do console baterem com isto.
"""
import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))            # research/deob
sys.path.insert(0, _HERE)                                     # -> import replay_capture
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))   # windows/ -> mitigus.deob

from mitigus.deob import Deobfuscator
from mitigus.deob.constants import LATEST
import replay_capture


def _make_initializer(deob, seed1, seed2, seed3):
    md = bytearray(64)
    md[2:4] = deob.constants.unknown_obfuscation_init_opcode.to_bytes(2, "little")
    md[22] = deob.constants.obfuscation_enabled_mode
    md[23] = seed1
    md[24] = seed2
    md[28:32] = (seed3 & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(md)


def _make_plaintext_action_effect(deob, action_id=0x1234, effect_count=5):
    md = bytearray(600)
    md[2:4] = deob.constants.obfuscated_opcodes["ActionEffect08"].to_bytes(2, "little")
    md[24:28] = action_id.to_bytes(4, "little")     # action_id (ofuscado)
    md[40:42] = (0x00AB).to_bytes(2, "little")       # source_sequence
    md[49] = effect_count                            # effect_count (não ofuscado)
    for i in range(effect_count):                    # valores de dano (ofuscados)
        md[64 + i * 8:64 + i * 8 + 2] = (1000 + i * 137).to_bytes(2, "little")
    return md


def _seg_record(direction, md):
    return {"dir": direction, "ts": 0, "conn": 1, "comp": 2,
            "mtype": 3, "src": 1, "tgt": 1,
            "itype": 0x0014, "op": int.from_bytes(md[2:4], "little"),
            "len": len(md), "data": bytes(md).hex()}


class ReplayEndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "synthetic.jsonl")

    def _write(self, records):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"_meta": "mitigus-capture", "v": 1}) + "\n")
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def test_recovers_action_effect(self):
        deob = Deobfuscator(LATEST)
        init = _make_initializer(deob, 0x5C, 0x1E, 0xA1B2C3D4)
        deob.feed_initializer(init)
        self.assertTrue(deob.is_active)
        keys = deob.keygen.keys
        okt = deob.keygen.opcode_key_table

        plain = _make_plaintext_action_effect(deob, action_id=0x1234, effect_count=5)
        wire = bytearray(plain)
        deob.unscrambler.scramble(wire, *keys, okt)   # simula o fio (ofuscado)
        self.assertNotEqual(bytes(wire), bytes(plain))

        self._write([_seg_record("s2c", init), _seg_record("s2c", wire)])

        n_effects, n_plausible = replay_capture.replay(self.path, LATEST)
        self.assertEqual(n_effects, 1)
        self.assertEqual(n_plausible, 1)

    def test_no_initializer_means_no_decode(self):
        deob = Deobfuscator(LATEST)
        init = _make_initializer(deob, 1, 2, 3)
        deob.feed_initializer(init)
        plain = _make_plaintext_action_effect(deob)
        wire = bytearray(plain)
        deob.unscrambler.scramble(wire, *deob.keygen.keys, deob.keygen.opcode_key_table)
        # captura SEM o inicializador -> não dá pra derivar chave -> não decodifica
        self._write([_seg_record("s2c", wire)])
        n_effects, n_plausible = replay_capture.replay(self.path, LATEST)
        self.assertEqual(n_effects, 0)  # is_active False -> pulou os ActionEffect


if __name__ == "__main__":
    unittest.main()
