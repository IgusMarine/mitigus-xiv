import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.meter.combat import (
    EFFECTS_AT,
    parse_action_effect,
)


def _put_entry(buf, off, etype, severity=0, value=0, flags=0, kind=0x71):
    buf[off + 0] = etype
    buf[off + 1] = severity
    buf[off + 2] = kind
    buf[off + 5] = flags
    buf[off + 6:off + 8] = (value & 0xFFFF).to_bytes(2, "little")


def make_action_effect(action_id, effects, seq=0x10, anim=0.6, effect_count=1, size=140):
    """effects: lista de (slot, type, severity, value)."""
    md = bytearray(size)
    md[24:28] = action_id.to_bytes(4, "little")
    md[32:36] = struct.pack("<f", anim)
    md[40:42] = seq.to_bytes(2, "little")
    md[49] = effect_count
    for slot, etype, sev, val in effects:
        _put_entry(md, EFFECTS_AT + slot * 8, etype, sev, val)
    return bytes(md)


class CombatParseTest(unittest.TestCase):
    def test_single_damage_crit_direct(self):
        md = make_action_effect(0x3f11, [(0, 0x03, 0x60, 12345)])
        ae = parse_action_effect(md, max_targets=1)
        self.assertEqual(ae.action_id, 0x3f11)
        self.assertEqual(ae.source_sequence, 0x10)
        self.assertAlmostEqual(ae.animation_lock, 0.6, places=5)
        self.assertEqual(ae.total_damage, 12345)
        dmg = [e for e in ae.effects if e.is_damage]
        self.assertEqual(len(dmg), 1)
        self.assertTrue(dmg[0].is_crit)
        self.assertTrue(dmg[0].is_direct)

    def test_severity_variants(self):
        cases = {0x00: (False, False), 0x20: (True, False),
                 0x40: (False, True), 0x60: (True, True)}
        for sev, (crit, dh) in cases.items():
            md = make_action_effect(0x100, [(0, 0x03, sev, 1000)])
            e = parse_action_effect(md, 1).effects[0]
            self.assertEqual((e.is_crit, e.is_direct), (crit, dh), f"sev={sev:#x}")

    def test_status_apply_is_not_damage(self):
        # type 0x0f = aplicar status; o "value" é ID do status, NÃO entra no dano
        md = make_action_effect(0x3f24, [(0, 0x03, 0x00, 5000), (1, 0x0f, 0x00, 1843)])
        ae = parse_action_effect(md, 1)
        self.assertEqual(ae.total_damage, 5000)   # só o 0x03
        self.assertEqual(len(ae.effects), 2)      # ambos parseados
        self.assertEqual(sum(e.is_damage for e in ae.effects), 1)

    def test_blocked_and_parried_count_as_damage(self):
        md = make_action_effect(0x200, [(0, 0x05, 0x00, 800), (1, 0x06, 0x00, 700)],
                                effect_count=1)
        ae = parse_action_effect(md, 1)
        self.assertEqual(ae.total_damage, 1500)

    def test_damage_over_65535(self):
        # regra canônica (Sapphire extendedValueHighestByte + cactbot 0x4000):
        # exemplo 423F com byte alto 0F e flag 0x40 -> 0x0F423F = 999999
        md = bytearray(140)
        md[24:28] = (0x1234).to_bytes(4, "little")
        md[49] = 1
        off = EFFECTS_AT
        md[off] = 0x03            # type = damage
        md[off + 4] = 0x0F        # extendedValueHighestByte
        md[off + 5] = 0x40        # flag 0x4000 (dano grande)
        md[off + 6:off + 8] = (0x423F).to_bytes(2, "little")
        ae = parse_action_effect(bytes(md), 1)
        self.assertEqual(ae.total_damage, 0x0F423F)  # 999999

    def test_no_overflow_when_flag_absent(self):
        md = bytearray(140)
        md[49] = 1
        off = EFFECTS_AT
        md[off] = 0x03
        md[off + 4] = 0x0F        # byte alto presente, MAS sem a flag
        md[off + 6:off + 8] = (5000).to_bytes(2, "little")
        ae = parse_action_effect(bytes(md), 1)
        self.assertEqual(ae.total_damage, 5000)      # ignora o byte alto

    def test_truncated_returns_none(self):
        self.assertIsNone(parse_action_effect(b"\x00" * 10, 1))

    def test_zero_effect_count_no_effects(self):
        md = make_action_effect(0x300, [(0, 0x03, 0, 999)], effect_count=0)
        ae = parse_action_effect(md, 1)
        self.assertEqual(ae.effect_count, 0)
        self.assertEqual(ae.effects, [])
        self.assertEqual(ae.total_damage, 0)


if __name__ == "__main__":
    unittest.main()
