import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.update import manual

_CS = """namespace Unscrambler.Constants.Versions;
public static partial class GameConstants
{
    [VersionConstant]
    public static VersionConstants For999()
    {
        return new VersionConstants
        {
            GameVersion = "2099.01.02.0003.0000",
            TableRadixes = [11, 22, 33],
            TableMax = [44, 55, 66],
            ObfuscationEnabledMode = 77,
            InitZoneOpcode = 0x111,
            UnknownObfuscationInitOpcode = 0x222,
            ObfuscatedOpcodes = new Dictionary<string, int>
            {
                { "PlayerSpawn", 0x10 },
                { "ActionEffect01", 0x20 },
                { "ActorControl", 0x30 }
            },
        };
    }
}
"""

_WEAVE = {
    "C2S_ActionRequest": "0x0111", "C2S_ActionRequestGroundTargeted": "0x0112",
    "S2C_ActionEffect01": "0x0201", "S2C_ActionEffect08": "0x0202",
    "S2C_ActionEffect16": "0x0203", "S2C_ActionEffect24": "0x0204",
    "S2C_ActionEffect32": "0x0205", "S2C_ActorCast": "0x0301",
    "S2C_ActorControl": "0x0302", "S2C_ActorControlSelf": "0x0303",
    "Common_UseOodleTcp": True, "Server_IpRange": "", "Server_PortRange": "",
}


class ManualOpcodesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._la = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.tmp
        # app_dir() -> pasta temporária (o manual do weave é gravado lá)
        self._app_dir = manual.app_dir
        manual.app_dir = lambda: self.tmp
        self._ensure = manual._ensure_bins   # sem rede nos testes

    def tearDown(self):
        manual.app_dir = self._app_dir
        manual._ensure_bins = self._ensure
        if self._la is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._la
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- parser do .cs ------------------------------------------------
    def test_parse_constants_cs(self):
        c = manual.parse_constants_cs(_CS)
        self.assertEqual(c["game_version"], "2099.01.02.0003.0000")
        self.assertEqual(c["obfuscation_enabled_mode"], 77)
        self.assertEqual(c["table_radixes"], [11, 22, 33])
        self.assertEqual(c["table_max"], [44, 55, 66])
        self.assertEqual(c["init_zone_opcode"], 0x111)
        self.assertEqual(c["unknown_obfuscation_init_opcode"], 0x222)
        self.assertEqual(c["obfuscated_opcodes"]["ActionEffect01"], 0x20)

    def test_parse_constants_cs_rejects_garbage(self):
        self.assertIsNone(manual.parse_constants_cs("isso nao e um constants"))

    # ---- weave --------------------------------------------------------
    def test_apply_weave_json_object(self):
        res = manual.apply_manual(json.dumps(_WEAVE))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["kind"], "weave")
        self.assertFalse(res["restart"])          # vale na hora
        path = manual.manual_weave_path()
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertIsInstance(saved, list)        # sempre lista (o loader aceita)
        self.assertEqual(saved[0]["S2C_ActionEffect01"], "0x0201")

    def test_apply_weave_list_and_loadable(self):
        # o arquivo gravado tem que ser carregavel pelo load_definitions real
        self.assertTrue(manual.apply_manual(json.dumps([_WEAVE, _WEAVE]))["ok"])
        from mitigus.protocol.opcodes import load_definitions
        defs = load_definitions(json_path=manual.manual_weave_path())
        self.assertEqual(len(defs), 2)
        self.assertTrue(defs[0].is_action_effect(0x0201))

    def test_apply_weave_invalid_is_rejected_and_nothing_written(self):
        bad = dict(_WEAVE)
        bad.pop("S2C_ActionEffect08")             # campo obrigatorio faltando
        res = manual.apply_manual(json.dumps(bad))
        self.assertFalse(res["ok"])
        self.assertFalse(os.path.exists(manual.manual_weave_path()))

    # ---- deob ---------------------------------------------------------
    def test_apply_deob_from_cs(self):
        calls = []
        manual._ensure_bins = lambda v, d, log: calls.append(v) or True
        res = manual.apply_manual(_CS)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["kind"], "deob")
        self.assertTrue(res["restart"])           # deob vale no proximo boot
        self.assertEqual(calls, ["2099.01.02.0003.0000"])
        vj = os.path.join(self.tmp, "Mitigus", "deob", "versions.json")
        with open(vj, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data[0]["game_version"], "2099.01.02.0003.0000")
        self.assertEqual(data[0]["keygen_gen"], "74")   # default preenchido

    def test_apply_deob_merges_and_is_loadable(self):
        manual._ensure_bins = lambda v, d, log: True
        self.assertTrue(manual.apply_manual(_CS)["ok"])
        other = dict(manual.parse_constants_cs(_CS))
        other["game_version"] = "2099.02.02.0000.0000"
        self.assertTrue(manual.apply_manual(json.dumps(other))["ok"])
        # o loader dinamico real tem que enxergar as duas
        from mitigus.deob import constants as C
        saved = dict(C.VERSIONS)
        try:
            C._load_dynamic_versions()
            self.assertIn("2099.01.02.0003.0000", C.VERSIONS)
            self.assertIn("2099.02.02.0000.0000", C.VERSIONS)
            self.assertEqual(C.LATEST, "2099.02.02.0000.0000")   # LATEST sobe
        finally:
            C.VERSIONS.clear()
            C.VERSIONS.update(saved)
            C.LATEST = max(saved, key=lambda v: tuple(int(x) for x in v.split(".")))

    def test_apply_deob_missing_bins_warns_but_saves(self):
        manual._ensure_bins = lambda v, d, log: False    # sem tabelas
        res = manual.apply_manual(_CS)
        self.assertTrue(res["ok"])
        self.assertEqual(res["bins_missing"], ["2099.01.02.0003.0000"])
        self.assertIn("tabelas", res["detail"])

    def test_apply_deob_incomplete_is_rejected(self):
        bad = manual.parse_constants_cs(_CS)
        bad.pop("table_radixes")
        res = manual.apply_manual(json.dumps(bad))
        self.assertFalse(res["ok"])
        self.assertIn("table_radixes", res["detail"])

    # ---- entradas ruins ------------------------------------------------
    def test_rejects_empty_and_unknown(self):
        self.assertFalse(manual.apply_manual("")["ok"])
        self.assertFalse(manual.apply_manual("   ")["ok"])
        self.assertFalse(manual.apply_manual('{"foo": 1}')["ok"])
        self.assertFalse(manual.apply_manual("<html>nope</html>")["ok"])

    # ---- pasta drop ----------------------------------------------------
    def test_drop_folder_applies_and_marks(self):
        manual._ensure_bins = lambda v, d, log: True
        d = manual.drop_dir()
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "weave.json"), "w", encoding="utf-8") as f:
            json.dump(_WEAVE, f)
        with open(os.path.join(d, "Constants999.cs"), "w", encoding="utf-8") as f:
            f.write(_CS)
        with open(os.path.join(d, "leiame.md"), "w", encoding="utf-8") as f:
            f.write("ignorar")                    # extensao nao suportada
        out = manual.apply_drop_folder()
        self.assertEqual(len(out), 2)
        self.assertTrue(all(r["ok"] for r in out), out)
        # aplicados sao renomeados, pra nao repetir no proximo boot
        self.assertTrue(os.path.exists(os.path.join(d, "weave.json.aplicado")))
        self.assertTrue(os.path.exists(os.path.join(d, "Constants999.cs.aplicado")))
        self.assertEqual(manual.apply_drop_folder(), [])

    def test_drop_folder_absent_is_noop(self):
        self.assertEqual(manual.apply_drop_folder(), [])


if __name__ == "__main__":
    unittest.main()
