import json
import os
import sys
import tempfile
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.panel.hub import ControlHub
from mitigus.panel.server import PanelServer


class HubTest(unittest.TestCase):
    def test_toggle_and_enable(self):
        h = ControlHub(enabled=True)
        self.assertTrue(h.is_enabled())
        self.assertFalse(h.toggle())
        self.assertTrue(h.toggle())
        self.assertFalse(h.set_enabled(False))

    def test_record_effect_accumulates(self):
        h = ControlHub()
        h.record_effect(600, 175, 250)
        h.record_effect(500, 400, 120)
        t = h.status()["telemetry"]
        self.assertEqual(t["last_original_ms"], 500)
        self.assertEqual(t["last_reduced_ms"], 400)
        self.assertEqual(t["last_saved_ms"], 100)
        self.assertEqual(t["last_rtt_ms"], 120)
        self.assertEqual(t["total_actions"], 2)
        self.assertEqual(t["total_saved_ms"], 525)  # 425 + 100

    def test_status_shape(self):
        s = ControlHub().status()
        for key in ("enabled", "flows", "uptime_s", "telemetry", "telemetry_age_s", "config", "info"):
            self.assertIn(key, s)

    def test_config_clamps_and_reports(self):
        h = ControlHub(extra_delay=0.075)
        self.assertAlmostEqual(h.extra_delay(), 0.075)
        h.set_config(extra_delay=0.5)  # acima do máximo
        self.assertAlmostEqual(h.extra_delay(), ControlHub.EXTRA_DELAY_MAX)
        h.set_config(extra_delay=0.01)  # abaixo do mínimo
        self.assertAlmostEqual(h.extra_delay(), ControlHub.EXTRA_DELAY_MIN)
        self.assertEqual(h.status()["config"]["extra_delay_ms"], int(ControlHub.EXTRA_DELAY_MIN * 1000))

    def test_info_in_status(self):
        h = ControlHub()
        h.set_info(mode="proxy", pc_ip="192.168.0.10", admin=True)
        info = h.status()["info"]
        self.assertEqual(info["pc_ip"], "192.168.0.10")
        self.assertTrue(info["admin"])


def _get(url):
    with urllib.request.urlopen(url, timeout=3) as r:
        return r.status, r.read()


def _post(url):
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.status, r.read()


class PanelServerTest(unittest.TestCase):
    def setUp(self):
        self.hub = ControlHub(enabled=True)
        self.srv = PanelServer(self.hub, host="127.0.0.1", port=0)
        self.port = self.srv.start()

    def tearDown(self):
        self.srv.stop()

    def _base(self):
        return f"http://127.0.0.1:{self.port}"

    def test_serves_index(self):
        code, body = _get(self._base() + "/")
        self.assertEqual(code, 200)
        self.assertIn(b"Mitigus", body)

    def test_status_json(self):
        code, body = _get(self._base() + "/api/status")
        self.assertEqual(code, 200)
        self.assertIn("enabled", json.loads(body))

    def test_toggle_and_enable_endpoints(self):
        _, body = _post(self._base() + "/api/toggle")
        self.assertFalse(json.loads(body)["enabled"])
        self.assertFalse(self.hub.is_enabled())
        _, body = _post(self._base() + "/api/enable?on=1")
        self.assertTrue(json.loads(body)["enabled"])
        self.assertTrue(self.hub.is_enabled())

    def test_config_endpoint(self):
        _, body = _post(self._base() + "/api/config?extra_delay_ms=90")
        self.assertEqual(json.loads(body)["extra_delay_ms"], 90)
        self.assertAlmostEqual(self.hub.extra_delay(), 0.09, places=4)

    def test_lang_endpoint(self):
        old = os.environ.get("LOCALAPPDATA")
        with tempfile.TemporaryDirectory() as d:  # não escreve no dir real do usuário
            os.environ["LOCALAPPDATA"] = d
            try:
                _, body = _post(self._base() + "/api/lang?lang=es")
                self.assertEqual(json.loads(body)["lang"], "es")
                _, body = _post(self._base() + "/api/lang?lang=xx")  # inválido -> en
                self.assertEqual(json.loads(body)["lang"], "en")
            finally:
                if old is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = old

    def test_opcodes_update_unavailable_without_handler(self):
        _, body = _post(self._base() + "/api/opcodes/update")
        self.assertFalse(json.loads(body)["ok"])  # sem handler -> não quebra

    def test_opcodes_update_calls_handler(self):
        calls = {"n": 0}

        def upd():
            calls["n"] += 1
            return {"ok": True, "count": 1, "date": "10/06/2026"}

        srv = PanelServer(ControlHub(), host="127.0.0.1", port=0, on_update_opcodes=upd)
        port = srv.start()
        try:
            _, body = _post(f"http://127.0.0.1:{port}/api/opcodes/update")
            d = json.loads(body)
            self.assertTrue(d["ok"])
            self.assertEqual(d["date"], "10/06/2026")
            self.assertEqual(calls["n"], 1)
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()
