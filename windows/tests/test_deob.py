"""
Testes do spike de desofuscacao.

O que ESTES testes provam (sem captura real / sem .NET):
  1. Round-trip: scramble -> unscramble recupera o original byte-a-byte, e o
     scramble REALMENTE mexe nos bytes. Valida offsets, dispatch por opcode,
     larguras e aritmetica do descramble (a parte mais erro-de-port).
  2. Derivacao de chave: determinismo + fiacao do pacote inicializador
     (byte de modo, offsets dos seeds, negacao de bits).

O que ELES NAO provam: que a chave derivada bate byte-a-byte com a do JOGO.
Isso so se valida com (a) captura real do PS5, ou (b) build do C# de
referencia (sem .NET SDK aqui). Ver README.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.deob import Deobfuscator             # noqa: E402
from mitigus.deob.constants import LATEST         # noqa: E402


def make_initializer(mode, seed1, seed2, seed3, size=64):
    pkt = bytearray(size)
    pkt[22] = mode
    pkt[23] = seed1
    pkt[24] = seed2
    pkt[28:32] = (seed3 & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(pkt)


def make_ipc(opcode, size=4096, fill=0xAB):
    buf = bytearray([fill]) * size
    buf[2:4] = (opcode & 0xFFFF).to_bytes(2, "little")
    return bytes(buf)


class KeyDerivationTest(unittest.TestCase):
    def setUp(self):
        self.deob = Deobfuscator(LATEST)
        self.mode = self.deob.constants.obfuscation_enabled_mode

    def test_initializer_enables_and_derives(self):
        active = self.deob.feed_initializer(
            make_initializer(self.mode, 0x11, 0x22, 0x33445566))
        self.assertTrue(active)
        self.assertTrue(self.deob.is_active)
        self.assertEqual(len(self.deob.keygen.keys), 3)
        for k in self.deob.keygen.keys:
            self.assertTrue(0 <= k <= 255)

    def test_mode_off_zeroes_keys(self):
        active = self.deob.feed_initializer(
            make_initializer(self.mode ^ 0xFF, 0x11, 0x22, 0x33445566))
        self.assertFalse(active)
        self.assertFalse(self.deob.is_active)
        self.assertEqual(self.deob.keygen.keys, [0, 0, 0])

    def test_deterministic(self):
        pkt = make_initializer(self.mode, 0x7A, 0x03, 0xDEADBEEF)
        self.deob.feed_initializer(pkt)
        k1 = list(self.deob.keygen.keys)
        d2 = Deobfuscator(LATEST)
        d2.feed_initializer(pkt)
        self.assertEqual(k1, list(d2.keygen.keys))

    def test_seed_offsets_matter(self):
        # mudar um seed muda as chaves (offsets corretos estao sendo lidos)
        self.deob.feed_initializer(make_initializer(self.mode, 1, 2, 3))
        a = list(self.deob.keygen.keys)
        self.deob.feed_initializer(make_initializer(self.mode, 9, 2, 3))
        b = list(self.deob.keygen.keys)
        self.assertNotEqual(a, b)


class RoundTripTest(unittest.TestCase):
    def setUp(self):
        self.deob = Deobfuscator(LATEST)
        self.deob.feed_initializer(
            make_initializer(self.deob.constants.obfuscation_enabled_mode,
                             0x5C, 0x1E, 0xA1B2C3D4))
        self.k = self.deob.keygen.keys
        self.okt = self.deob.keygen.opcode_key_table
        # precisa de chave nao-nula senao unscramble e no-op
        self.assertTrue(any(self.k), "chaves derivadas sairam todas zero")

    def _roundtrip(self, opcode):
        op = self.deob.constants.obfuscated_opcodes[opcode]
        original = make_ipc(op)

        scrambled = bytearray(original)
        self.deob.unscrambler.scramble(scrambled, *self.k, self.okt)
        self.assertNotEqual(bytes(scrambled), original,
                            f"{opcode}: scramble nao alterou nada")

        recovered = bytearray(scrambled)
        self.deob.unscrambler.unscramble(recovered, *self.k, self.okt)
        self.assertEqual(bytes(recovered), original,
                         f"{opcode}: round-trip nao recuperou o original")

    def test_action_effect_variants(self):
        for op in ("ActionEffect01", "ActionEffect08", "ActionEffect16",
                   "ActionEffect24", "ActionEffect32",
                   "ActionEffect02", "ActionEffect04"):
            with self.subTest(op=op):
                self._roundtrip(op)

    def test_player_spawn(self):
        self._roundtrip("PlayerSpawn")

    def test_npc_spawn(self):
        self._roundtrip("NpcSpawn")
        self._roundtrip("NpcSpawn2")

    def test_status_effect_list(self):
        self._roundtrip("StatusEffectList")
        self._roundtrip("StatusEffectList3")

    def test_actor_cast(self):
        self._roundtrip("ActorCast")

    def test_other_obfuscated(self):
        for op in ("Examine", "UpdateGearset", "UpdateParty",
                   "UnknownEffect01", "UnknownEffect16"):
            with self.subTest(op=op):
                self._roundtrip(op)

    def test_unscramble_copy_keeps_original_intact(self):
        op = self.deob.constants.obfuscated_opcodes["ActionEffect08"]
        # simula um pacote ofuscado: pega um limpo e embaralha
        clean = make_ipc(op)
        wire = bytearray(clean)
        self.deob.unscrambler.scramble(wire, *self.k, self.okt)
        wire_bytes = bytes(wire)

        out = self.deob.unscramble_copy(wire_bytes)
        self.assertEqual(bytes(wire), wire_bytes, "buffer original foi alterado")
        self.assertEqual(bytes(out), clean, "copia nao foi desofuscada certo")


if __name__ == "__main__":
    d = Deobfuscator(LATEST)
    d.feed_initializer(make_initializer(d.constants.obfuscation_enabled_mode,
                                        0x5C, 0x1E, 0xA1B2C3D4))
    print(f"versao .......... {d.game_version}")
    print(f"ofuscacao ativa . {d.is_active}")
    print(f"chaves derivadas  {[hex(k) for k in d.keygen.keys]}")
    print(f"opcode key table  {len(d.keygen.opcode_key_table)} entradas")
    print(f"opcodes ofusc. .. {len(d.constants.obfuscated_opcodes)}")
    print()
    unittest.main()
