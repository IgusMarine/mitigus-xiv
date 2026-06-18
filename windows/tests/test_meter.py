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


def make_dot_wire(deob, caster, amount, cat=0x605):
    """Tick de DoT via ActorControl. A categoria 0x605 (DoT) é texto-claro (o
    deob não a toca), então NÃO precisa ofuscar: param2@24=dano, param3@28=caster."""
    md = bytearray(40)
    md[2:4] = deob.constants.obfuscated_opcodes["ActorControl"].to_bytes(2, "little")
    md[16:18] = (cat & 0xFFFF).to_bytes(2, "little")
    md[24:28] = (amount & 0xFFFFFFFF).to_bytes(4, "little")    # param2 = dano
    md[28:32] = (caster & 0xFFFFFFFF).to_bytes(4, "little")    # param3 = caster
    md[32:36] = (0xFFFFFFFF).to_bytes(4, "little")             # param4 sentinela
    return bytes(md)


def make_npc_spawn_wire(deob, owner, which="NpcSpawn"):
    """NpcSpawn JÁ ofuscado com Companion Owner@96 (o id do pet vem do src do
    segmento, não do corpo)."""
    md = bytearray(560)
    md[2:4] = deob.constants.obfuscated_opcodes[which].to_bytes(2, "little")
    md[96:100] = (owner & 0xFFFFFFFF).to_bytes(4, "little")    # Companion Owner
    deob.unscrambler.scramble(md, *deob.keygen.keys, deob.keygen.opcode_key_table)
    return bytes(md)


def make_status_wire(deob, op_name, entries, src=0xAA):
    """entries: list of dicts: {'status_id': ..., 'stacks': ..., 'duration': ..., 'caster_id': ...}"""
    md = bytearray(400)
    md[2:4] = deob.constants.obfuscated_opcodes[op_name].to_bytes(2, "little")
    op_offset = 36 if op_name == "StatusEffectList" else 16
    for i, s in enumerate(entries):
        base = op_offset + i * 12
        if base + 12 > len(md):
            break
        md[base:base+2] = s["status_id"].to_bytes(2, "little")
        md[base+2] = s["stacks"]
        struct.pack_into("<f", md, base+4, float(s["duration"]))
        md[base+8:base+12] = s["caster_id"].to_bytes(4, "little")
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

    def test_dot_credited_to_caster_not_target(self):
        # tick de DoT: o src do segmento é o ALVO; o crédito vai pro caster (param3).
        feed = MeterFeed()
        feed.feed_record(rec(self.init, src=1, ts=0))
        feed.feed_record(rec(make_dot_wire(self.gen, caster=0xAA, amount=1234),
                             src=0xBEEF, ts=1000))   # src = inimigo
        snap = feed.tracker.snapshot()
        self.assertEqual(snap["total_damage"], 1234)
        ids = [a["id"] for a in snap["actors"]]
        self.assertIn(0xAA, ids)            # creditado ao caster
        self.assertNotIn(0xBEEF, ids)       # NÃO ao alvo (src)
        a = next(a for a in snap["actors"] if a["id"] == 0xAA)
        self.assertEqual(a["damage"], 1234)
        self.assertEqual(a["hits"], 0)      # DoT não conta como hit
        self.assertEqual(a["crit"], 0.0)

    def test_dot_works_without_initializer(self):
        # ActorControl cat 0x605 é texto-claro -> DoT funciona mesmo sem a chave.
        feed = MeterFeed()
        feed.feed_record(rec(make_dot_wire(self.gen, caster=0xAA, amount=500),
                             src=0xBEEF, ts=1000))
        self.assertEqual(feed.tracker.snapshot()["total_damage"], 500)

    def test_other_actorcontrol_categories_ignored(self):
        # HoT (0x604), TargetIcon (34) e outras categorias NÃO entram no DPS.
        feed = MeterFeed()
        feed.feed_record(rec(self.init, src=1, ts=0))
        for cat in (0x604, 34, 0, 0x15):
            feed.feed_record(rec(make_dot_wire(self.gen, caster=0xAA, amount=999, cat=cat),
                                 src=0xBEEF, ts=1000))
        self.assertEqual(feed.tracker.snapshot()["total_damage"], 0)

    def test_pet_damage_rolls_into_owner(self):
        # NpcSpawn marca pet->dono; o ActionEffect do pet soma na linha do dono,
        # sem criar uma linha-fantasma do pet.
        feed = MeterFeed()
        feed.feed_record(rec(self.init, src=1, ts=0))
        feed.feed_record(rec(make_npc_spawn_wire(self.gen, owner=0x1006),
                             src=0x4000, ts=0))       # pet id = 0x4000, dono = 0x1006
        feed.feed_record(rec(make_ae_wire(self.gen, 0x100, [(0, 0x03, 0, 7000)]),
                             src=0x4000, ts=1000))    # dano do pet
        snap = feed.tracker.snapshot()
        self.assertEqual([a["id"] for a in snap["actors"]], [0x1006])  # só o dono
        self.assertEqual(snap["actors"][0]["damage"], 7000)

    def test_recycled_id_cleared_when_respawned_as_npc(self):
        # ID de pet reciclada como NPC comum (owner=0) limpa o mapeamento, senão
        # o dano do novo inimigo seria creditado ao dono antigo.
        feed = MeterFeed()
        feed.feed_record(rec(self.init, src=1, ts=0))
        feed.feed_record(rec(make_npc_spawn_wire(self.gen, owner=0x1006),
                             src=0x4000, ts=0))         # pet 0x4000 -> dono 0x1006
        feed.feed_record(rec(make_npc_spawn_wire(self.gen, owner=0),
                             src=0x4000, ts=100))       # 0x4000 reciclada (NPC comum)
        feed.feed_record(rec(make_ae_wire(self.gen, 0x100, [(0, 0x03, 0, 3000)]),
                             src=0x4000, ts=1000))      # dano agora é do próprio 0x4000
        ids = [a["id"] for a in feed.tracker.snapshot()["actors"]]
        self.assertIn(0x4000, ids)
        self.assertNotIn(0x1006, ids)                  # dono antigo NÃO recebe

    def test_rdps_divination_aoe_buff(self):
        feed = MeterFeed()
        # Feed the initializer first so deobfuscation is active
        feed.feed_record(rec(self.init, src=1, ts=0))
        # Start combat at ts=0 with a dummy 1-damage hit
        dummy_ae = make_ae_wire(self.gen, 0x100, [(0, 0x03, 0, 1)], seq=1)
        feed.feed_record(rec(dummy_ae, src=0x2222, ts=0))

        # Player A (0x1111) applies Divination (ID 1878, AoE mult, 6%) on Player B (0x2222)
        status_entries = [{"status_id": 1878, "stacks": 0, "duration": 20.0, "caster_id": 0x1111}]
        status_wire = make_status_wire(self.gen, "StatusEffectList", status_entries, src=0x2222)
        feed.feed_record(rec(status_wire, src=0x2222, ts=1000))
        
        # Player B (0x2222) does 1060 damage (non-crit, non-direct)
        ae_wire = make_ae_wire(self.gen, 0x100, [(0, 0x03, 0, 1060)], seq=1)
        feed.feed_record(rec(ae_wire, src=0x2222, ts=1500))
        
        snap = feed.tracker.snapshot()
        self.assertEqual(snap["total_damage"], 1061)
        
        actors = {a["id"]: a for a in snap["actors"]}
        actor_b = actors[0x2222]
        actor_a = actors[0x1111]
        
        self.assertEqual(actor_b["damage"], 1061)
        self.assertEqual(actor_a["damage"], 0)
        
        # B's raw neutral = 1000 (from 1060/1.06) + 1 (from dummy) = 1001
        self.assertAlmostEqual(actor_b["ndps"] * 1.5, 1001.0, delta=2.0)
        # B's raw adps = 1060 (since divination is AoE) + 1 = 1061
        self.assertAlmostEqual(actor_b["adps"] * 1.5, 1061.0, delta=2.0)
        # B's raw rdps = 1001
        self.assertAlmostEqual(actor_b["rdps"] * 1.5, 1001.0, delta=2.0)
        # A's raw rdps = 60
        self.assertAlmostEqual(actor_a["rdps"] * 1.5, 60.0, delta=2.0)
        
        # Total rDPS sum check: 1001 + 60 = 1061 (equal to total damage)
        total_rdps = sum(a["rdps"] for a in snap["actors"])
        self.assertAlmostEqual(total_rdps * 1.5, 1061.0, delta=2.0)

    def test_rdps_standard_finish_single_buff(self):
        feed = MeterFeed()
        # Feed the initializer first so deobfuscation is active
        feed.feed_record(rec(self.init, src=1, ts=0))
        # Start combat at ts=0 with a dummy 1-damage hit
        dummy_ae = make_ae_wire(self.gen, 0x100, [(0, 0x03, 0, 1)], seq=1)
        feed.feed_record(rec(dummy_ae, src=0x2222, ts=0))

        # Player A (0x1111) applies Standard Finish (ID 2105, single-target mult, 5%) on Player B (0x2222)
        status_entries = [{"status_id": 2105, "stacks": 0, "duration": 20.0, "caster_id": 0x1111}]
        status_wire = make_status_wire(self.gen, "StatusEffectList", status_entries, src=0x2222)
        feed.feed_record(rec(status_wire, src=0x2222, ts=1000))
        
        # Player B (0x2222) does 1050 damage (non-crit, non-direct)
        ae_wire = make_ae_wire(self.gen, 0x100, [(0, 0x03, 0, 1050)], seq=1)
        feed.feed_record(rec(ae_wire, src=0x2222, ts=1500))
        
        snap = feed.tracker.snapshot()
        self.assertEqual(snap["total_damage"], 1051)
        
        actors = {a["id"]: a for a in snap["actors"]}
        actor_b = actors[0x2222]
        actor_a = actors[0x1111]
        
        # B's raw neutral = 1000 (from 1050/1.05) + 1 = 1001
        self.assertAlmostEqual(actor_b["ndps"] * 1.5, 1001.0, delta=2.0)
        # B's raw adps = 1000 (standard finish is single, so excluded) + 1 = 1001
        self.assertAlmostEqual(actor_b["adps"] * 1.5, 1001.0, delta=2.0)
        # B's raw rdps = 1001
        self.assertAlmostEqual(actor_b["rdps"] * 1.5, 1001.0, delta=2.0)
        # A's raw rdps = 50
        self.assertAlmostEqual(actor_a["rdps"] * 1.5, 50.0, delta=2.0)

    def test_rdps_battle_litany_crit_buff(self):
        feed = MeterFeed()
        # Feed the initializer first so deobfuscation is active
        feed.feed_record(rec(self.init, src=1, ts=0))
        # Start combat at ts=0 with a dummy 1-damage hit
        dummy_ae = make_ae_wire(self.gen, 0x100, [(0, 0x03, 0, 1)], seq=1)
        feed.feed_record(rec(dummy_ae, src=0x2222, ts=0))

        # Player A (0x1111) applies Battle Litany (ID 786, AoE crit, 10%) on Player B (0x2222)
        status_entries = [{"status_id": 786, "stacks": 0, "duration": 20.0, "caster_id": 0x1111}]
        status_wire = make_status_wire(self.gen, "StatusEffectList", status_entries, src=0x2222)
        feed.feed_record(rec(status_wire, src=0x2222, ts=1000))
        
        # Player B (0x2222) does 1500 damage (crit, non-direct)
        ae_wire = make_ae_wire(self.gen, 0x100, [(0, 0x03, 0x20, 1500)], seq=1) # severity 0x20 = crit
        feed.feed_record(rec(ae_wire, src=0x2222, ts=1500))
        
        snap = feed.tracker.snapshot()
        self.assertEqual(snap["total_damage"], 1501)
        
        actors = {a["id"]: a for a in snap["actors"]}
        actor_b = actors[0x2222]
        actor_a = actors[0x1111]
        
        # Base damage = 1500 / 1.5 = 1000.
        # Crit gain = 1500 - 1000 = 500.
        # Share of Battle Litany = 10% / (15% natural + 10% buff) = 0.40.
        # Gain of Battle Litany = 500 * 0.4 = 200.
        # Neutral of B: 1500 - 200 = 1300 + 1 (dummy) = 1301.
        self.assertAlmostEqual(actor_b["ndps"] * 1.5, 1301.0, delta=2.0)
        # aDPS of B: keeps Battle Litany gain since it's AoE. 1500 + 1 = 1501.
        self.assertAlmostEqual(actor_b["adps"] * 1.5, 1501.0, delta=2.0)
        # rDPS of B: neutral = 1301.
        self.assertAlmostEqual(actor_b["rdps"] * 1.5, 1301.0, delta=2.0)
        # A's raw rdps = 200.
        self.assertAlmostEqual(actor_a["rdps"] * 1.5, 200.0, delta=2.0)


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

    def test_pet_owner_resolve_survives_reset(self):
        # mapa pet->dono é persistente: o dano do pet não pode virar linha-fantasma
        # depois de uma nova luta.
        t = DpsTracker(idle_reset_s=10.0)
        t.set_pet_owner(0x4000, 0x1006)
        self.assertEqual(t.resolve(0x4000), 0x1006)
        self.assertEqual(t.resolve(0x1006), 0x1006)   # não-pet: ele mesmo
        t.record_damage(0x1006, 100, ts_ms=0)
        t.record_damage(0x1006, 50, ts_ms=20000)      # +20s idle -> nova luta
        self.assertEqual(t.resolve(0x4000), 0x1006)   # mapeamento PERSISTE

    def test_resolve_pet_inside_record_damage(self):
        # resolve_pet=True resolve pet->dono atomicamente dentro do lock.
        t = DpsTracker()
        t.set_pet_owner(0x4000, 0x1006)
        t.record_damage(0x4000, 500, ts_ms=0, resolve_pet=True)
        a = t.snapshot()["actors"][0]
        self.assertEqual(a["id"], 0x1006)             # creditado ao dono
        self.assertEqual(a["damage"], 500)

    def test_clear_pet_owner(self):
        t = DpsTracker()
        t.set_pet_owner(0x4000, 0x1006)
        self.assertEqual(t.resolve(0x4000), 0x1006)
        t.clear_pet_owner(0x4000)
        self.assertEqual(t.resolve(0x4000), 0x4000)   # volta a ser ele mesmo

    def test_dot_damage_not_counted_as_hit(self):
        # count_hit=False: DoT soma no dano mas não dilui crit%/DH%.
        t = DpsTracker()
        t.record_damage(0xA, 1000, is_crit=True, ts_ms=0)        # 1 hit, crit
        t.record_damage(0xA, 500, ts_ms=1000, count_hit=False)  # DoT: só dano
        a = t.snapshot()["actors"][0]
        self.assertEqual(a["damage"], 1500)
        self.assertEqual(a["hits"], 1)
        self.assertEqual(a["crit"], 100.0)            # 1/1 — DoT não entrou no ratio


if __name__ == "__main__":
    unittest.main()
