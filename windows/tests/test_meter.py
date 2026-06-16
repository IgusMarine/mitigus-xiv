import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.deob import Deobfuscator
from mitigus.deob.constants import LATEST
from mitigus.meter.combat import EFFECTS_AT
from mitigus.meter.spawn import CLASSJOB_OFFSET, LEVEL_OFFSET
from mitigus.meter.live import MeterFeed
from mitigus.meter.tracker import DpsTracker


def make_init(deob, s1, s2, s3):
    md = bytearray(64)
    md[2:4] = deob.constants.unknown_obfuscation_init_opcode.to_bytes(2, "little")
    md[22] = deob.constants.obfuscation_enabled_mode
    md[23] = s1
    md[24] = s2
    md[28:32] = (s3 & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(md)


def make_ae_wire(deob, action_id, entries, effect_count=1, seq=0x10):
    """entries: lista (slot, type, severity, value). Devolve bytes JÁ ofuscados."""
    md = bytearray(140)
    md[2:4] = deob.constants.obfuscated_opcodes["ActionEffect01"].to_bytes(2, "little")
    md[24:28] = action_id.to_bytes(4, "little")
    md[32:36] = struct.pack("<f", 0.6)
    md[40:42] = (seq & 0xFFFF).to_bytes(2, "little")
    md[49] = effect_count
    for slot, etype, sev, val in entries:
        off = EFFECTS_AT + slot * 8
        md[off] = etype
        md[off + 1] = sev
        md[off + 6:off + 8] = (val & 0xFFFF).to_bytes(2, "little")
    deob.unscrambler.scramble(md, *deob.keygen.keys, deob.keygen.opcode_key_table)
    return bytes(md)


def make_spawn_wire(deob, name, classjob, level=100):
    """PlayerSpawn JÁ ofuscado: nome@610 + level + classJob."""
    md = bytearray(680)
    md[2:4] = deob.constants.obfuscated_opcodes["PlayerSpawn"].to_bytes(2, "little")
    nb = name.encode("utf-8")[:32]
    md[610:610 + len(nb)] = nb
    md[LEVEL_OFFSET] = level
    md[CLASSJOB_OFFSET] = classjob
    deob.unscrambler.scramble(md, *deob.keygen.keys, deob.keygen.opcode_key_table)
    return bytes(md)


def rec(md, src, ts, direction="s2c"):
    return {"dir": direction, "ts": ts, "src": src,
            "op": int.from_bytes(md[2:4], "little"), "data": bytes(md).hex()}


class MeterFeedTest(unittest.TestCase):
    def setUp(self):
        # deob "do servidor" p/ gerar os bytes ofuscados de teste
        self.gen = Deobfuscator(LATEST)
        self.init = make_init(self.gen, 0x5C, 0x1E, 0xA1B2C3D4)
        self.gen.feed_initializer(self.init)
        self.assertTrue(self.gen.is_active)

    def test_aggregates_damage_from_capture_records(self):
        feed = MeterFeed()                      # tem o PRÓPRIO deob
        ae = make_ae_wire(self.gen, 0x3f11,
                          [(0, 0x03, 0x20, 1000),   # crit
                           (1, 0x03, 0x00, 2000)])  # normal
        feed.feed_record(rec(self.init, src=0xABCD, ts=0))
        feed.feed_record(rec(ae, src=0xABCD, ts=1000))

        snap = feed.tracker.snapshot()
        self.assertEqual(snap["total_damage"], 3000)
        self.assertEqual(len(snap["actors"]), 1)
        a = snap["actors"][0]
        self.assertEqual(a["id"], 0xABCD)
        self.assertEqual(a["damage"], 3000)
        self.assertEqual(a["hits"], 2)
        self.assertEqual(a["crit"], 50.0)        # 1 de 2

    def test_no_decode_without_initializer(self):
        feed = MeterFeed()
        ae = make_ae_wire(self.gen, 0x3f11, [(0, 0x03, 0x00, 5000)])
        feed.feed_record(rec(ae, src=1, ts=1000))   # sem init -> sem chave
        self.assertEqual(feed.tracker.snapshot()["total_damage"], 0)

    def test_c2s_ignored(self):
        feed = MeterFeed()
        ae = make_ae_wire(self.gen, 0x3f11, [(0, 0x03, 0x00, 5000)])
        feed.feed_record(rec(self.init, src=1, ts=0))
        feed.feed_record(rec(ae, src=1, ts=1000, direction="c2s"))  # C2S não conta
        self.assertEqual(feed.tracker.snapshot()["total_damage"], 0)

    def test_two_actors_ranked_by_damage(self):
        feed = MeterFeed()
        feed.feed_record(rec(self.init, src=1, ts=0))
        feed.feed_record(rec(make_ae_wire(self.gen, 0x100, [(0, 0x03, 0, 500)]), src=0xA, ts=1000))
        feed.feed_record(rec(make_ae_wire(self.gen, 0x101, [(0, 0x03, 0, 9000)]), src=0xB, ts=2000))
        snap = feed.tracker.snapshot()
        self.assertEqual([a["id"] for a in snap["actors"]], [0xB, 0xA])  # maior dano 1º
        self.assertEqual(snap["total_damage"], 9500)


    def test_player_spawn_sets_name_job_level(self):
        feed = MeterFeed()
        feed.feed_record(rec(self.init, src=0x1006, ts=0))
        feed.feed_record(rec(make_spawn_wire(self.gen, "Igus Marine", 37, level=100), src=0x1006, ts=0))
        feed.feed_record(rec(make_ae_wire(self.gen, 0x3f11, [(0, 0x03, 0, 1000)]), src=0x1006, ts=1000))
        a = feed.tracker.snapshot()["actors"][0]
        self.assertEqual(a["name"], "Igus Marine")
        self.assertEqual(a["job"], "GNB")
        self.assertEqual(a["level"], 100)

    def test_self_detected_via_sequence(self):
        feed = MeterFeed()
        feed.feed_record(rec(self.init, src=1, ts=0))
        # server-originated (seq 0, ex.: auto-attack relayado) -> NÃO é você
        feed.feed_record(rec(make_ae_wire(self.gen, 0x0007, [(0, 0x03, 0, 100)], seq=0), src=0xEE, ts=1000))
        # ação sua (seq != 0) -> você
        feed.feed_record(rec(make_ae_wire(self.gen, 0x3f11, [(0, 0x03, 0, 5000)], seq=7), src=0xAA, ts=1100))
        byid = {a["id"]: a for a in feed.tracker.snapshot()["actors"]}
        self.assertTrue(byid[0xAA]["is_self"])
        self.assertFalse(byid[0xEE]["is_self"])


    def test_top_action_is_highest_damage(self):
        from mitigus.meter.names import action_name
        feed = MeterFeed()
        feed.feed_record(rec(self.init, src=1, ts=0))
        feed.feed_record(rec(make_ae_wire(self.gen, 16137, [(0, 0x03, 0, 1000)]), src=0xAA, ts=1000))
        feed.feed_record(rec(make_ae_wire(self.gen, 36937, [(0, 0x03, 0, 9000)]), src=0xAA, ts=1100))
        a = feed.tracker.snapshot()["actors"][0]
        self.assertEqual(a["top_action"], action_name(36937))  # robusto c/ ou sem actions.json


class DpsTrackerTest(unittest.TestCase):
    def test_idle_reset_starts_new_encounter(self):
        t = DpsTracker(idle_reset_s=10.0)
        t.record_damage(1, 100, ts_ms=0)
        t.record_damage(1, 100, ts_ms=5000)          # mesma luta (5s)
        self.assertEqual(t.snapshot()["total_damage"], 200)
        t.record_damage(1, 50, ts_ms=20000)          # +15s idle -> nova luta
        snap = t.snapshot()
        self.assertEqual(snap["total_damage"], 50)
        self.assertEqual(t.encounters, 2)

    def test_identity_survives_reset(self):
        # bug observado: trocar de luta apagava nome/job/level. Identidade persiste.
        t = DpsTracker(idle_reset_s=10.0)
        t.set_actor_info(0xA, name="Igus Marine", job="GNB", level=100)
        t.record_damage(0xA, 100, ts_ms=0)
        t.record_damage(0xA, 50, ts_ms=20000)   # +20s idle -> nova luta
        a = t.snapshot()["actors"][0]
        self.assertEqual(a["damage"], 50)        # stats zeraram (luta nova)
        self.assertEqual(a["name"], "Igus Marine")  # identidade PERSISTE
        self.assertEqual(a["job"], "GNB")
        self.assertEqual(a["level"], 100)

    def test_dps_and_pct(self):
        t = DpsTracker()
        t.record_damage(0xA, 1000, ts_ms=0)
        t.record_damage(0xA, 1000, ts_ms=2000)       # 2s -> 2000 dano
        snap = t.snapshot()
        self.assertEqual(snap["duration"], 2.0)
        self.assertEqual(snap["actors"][0]["dps"], 1000.0)
        self.assertEqual(snap["actors"][0]["pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
