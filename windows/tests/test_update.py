import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.update import updater


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_la = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.tmp
        self._old_get = updater._http_get

    def tearDown(self):
        updater._http_get = self._old_get
        if self._old_la is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old_la
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_vtuple_compare(self):
        self.assertTrue(updater._vtuple("0.2.0") > updater._vtuple("0.1.9"))
        self.assertTrue(updater._vtuple("2026.06.18.0000.0000")
                        > updater._vtuple("2026.06.10.0000.0000"))
        self.assertEqual(updater._vtuple("nan"), ())

    def test_app_update_available(self):
        import mitigus
        cur = mitigus.__version__
        parts = cur.split(".")
        nxt = ".".join([str(int(parts[0]) + 1)] + parts[1:])
        self.assertFalse(updater.app_update_available({"app_version": cur}))
        self.assertTrue(updater.app_update_available({"app_version": nxt}))
        self.assertFalse(updater.app_update_available({}))

    def test_sync_rev_file_downloads_then_skips(self):
        calls = {"n": 0}

        def fake_get(url, timeout=30.0):
            calls["n"] += 1
            return b'{"786": {"name": "X", "type": "crit", "value": 0.1}}'
        updater._http_get = fake_get

        m = {"buffs_url": "http://x/buffs.json", "buffs_rev": "abc"}
        self.assertIn("buffs", updater.sync_data(m))
        dest = os.path.join(self.tmp, "Mitigus", "meter", "buffs.json")
        self.assertTrue(os.path.exists(dest))

        n0 = calls["n"]
        self.assertNotIn("buffs", updater.sync_data(m))   # mesmo rev -> nao baixa
        self.assertEqual(calls["n"], n0)

        m["buffs_rev"] = "def"
        self.assertIn("buffs", updater.sync_data(m))       # rev novo -> baixa

    def test_sync_deob_constants_and_bins(self):
        def fake_get(url, timeout=30.0):
            if url.endswith("versions.json"):
                return (b'[{"game_version":"9.9.9","obfuscation_enabled_mode":1,'
                        b'"table_radixes":[1,2,3],"table_max":[1,2,3],'
                        b'"init_zone_opcode":1,"unknown_obfuscation_init_opcode":1,'
                        b'"obfuscated_opcodes":{}}]')
            return b"\x00\x01\x02\x03"
        updater._http_get = fake_get

        m = {"deob_version": "9.9.9",
             "deob_constants_url": "http://x/versions.json",
             "deob_base_url": "http://x/data/"}
        self.assertTrue(any("deob" in c for c in updater.sync_data(m)))
        deob = os.path.join(self.tmp, "Mitigus", "deob")
        self.assertTrue(os.path.exists(os.path.join(deob, "versions.json")))
        for b in updater._DEOB_BINS:
            self.assertTrue(os.path.exists(os.path.join(deob, "data", "9.9.9", b)))
        # 2a vez: .bin ja existem -> nao re-marca deob como mudado
        self.assertFalse(any("deob" in c for c in updater.sync_data(m)))

    def test_find_app_folder(self):
        staged = os.path.join(self.tmp, "staged")
        sub = os.path.join(staged, "Mitigus XIV App")
        os.makedirs(sub)
        open(os.path.join(sub, "Mitigus XIV App.exe"), "wb").close()
        self.assertEqual(updater._find_app_folder(staged), sub)
        self.assertIsNone(updater._find_app_folder(os.path.join(self.tmp, "vazio"))
                          if os.path.isdir(os.path.join(self.tmp, "vazio")) else None)

    def test_apply_pending_noop_when_not_frozen(self):
        # fora do .exe (testes), apply nunca age
        self.assertFalse(updater.apply_pending_update())

    def test_safe_extract_rejects_zip_slip(self):
        import zipfile
        zp = os.path.join(self.tmp, "evil.zip")
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("ok.txt", "hi")
            z.writestr("../escape.txt", "evil")   # tenta escapar do destino
        with zipfile.ZipFile(zp) as z:
            with self.assertRaises(ValueError):
                updater._safe_extract(z, os.path.join(self.tmp, "out"))

    def test_sync_deob_skips_bundled_version(self):
        called = {"n": 0}

        def fake_get(url, timeout=30.0):
            called["n"] += 1
            return b"x"
        updater._http_get = fake_get
        # versao real ja embutida no build -> _sync_deob pula sem tocar a rede
        m = {"deob_version": "2026.06.18.0000.0000",
             "deob_constants_url": "http://x/versions.json",
             "deob_base_url": "http://x/data/"}
        changed = updater.sync_data(m)
        self.assertNotIn("deob 2026.06.18.0000.0000", changed)
        self.assertEqual(called["n"], 0)

    def test_buffs_override_from_localappdata(self):
        from mitigus.meter import tracker
        saved = dict(tracker.BUFFS)
        try:
            p = os.path.join(self.tmp, "Mitigus", "meter", "buffs.json")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"9999": {"name": "Teste", "type": "mult", "value": 0.5}}, f)
            tracker._apply_buffs_override()
            self.assertIn(9999, tracker.BUFFS)
            self.assertEqual(tracker.BUFFS[9999]["value"], 0.5)
        finally:
            tracker.BUFFS.clear()
            tracker.BUFFS.update(saved)


if __name__ == "__main__":
    unittest.main()
