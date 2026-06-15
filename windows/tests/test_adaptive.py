import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.mitigation.mitigator import Mitigator
from mitigus.panel.hub import ControlHub


def _mit(**kw):
    # opcodes mínimo: o __init__ só lê Common_UseOodleTcp
    op = type("O", (), {"Common_UseOodleTcp": False})()
    return Mitigator(op, extra_delay=0.075, **kw)


class AdaptiveMarginTest(unittest.TestCase):
    def test_stable_line_keeps_base_margin(self):
        m = _mit(adaptive=True, adaptive_k=1.0, adaptive_max=0.20)
        for _ in range(10):
            m.latency_application.add(0.300)  # rtt constante -> desvio ~0
        margin, msg = m.resolve_adjusted_extra_delay(0.300)
        self.assertAlmostEqual(margin, 0.075, places=6)  # == base
        self.assertIn("margin=", msg)

    def test_jittery_line_grows_margin(self):
        m = _mit(adaptive=True, adaptive_k=1.0, adaptive_max=0.20)
        for v in (0.10, 0.50, 0.10, 0.50, 0.10, 0.50):  # muito jitter
            m.latency_application.add(v)
        margin, _ = m.resolve_adjusted_extra_delay(0.50)
        self.assertGreater(margin, 0.075)     # margem cresceu
        self.assertLessEqual(margin, 0.20)    # respeitou o teto

    def test_cap_is_enforced(self):
        m = _mit(adaptive=True, adaptive_k=100.0, adaptive_max=0.20)
        for v in (0.0, 1.0, 0.0, 1.0):
            m.latency_application.add(v)
        margin, _ = m.resolve_adjusted_extra_delay(1.0)
        self.assertEqual(margin, 0.20)

    def test_adaptive_off_returns_base(self):
        m = _mit(adaptive=False)
        for v in (0.1, 0.9, 0.1, 0.9):
            m.latency_application.add(v)
        margin, msg = m.resolve_adjusted_extra_delay(0.9)
        self.assertEqual(margin, m.extra_delay)
        self.assertEqual(msg, "")

    def test_never_below_base(self):
        m = _mit(adaptive=True, adaptive_k=1.0)
        m.latency_application.add(0.3)
        margin, _ = m.resolve_adjusted_extra_delay(0.3)
        self.assertGreaterEqual(margin, 0.075)


class HubPingTest(unittest.TestCase):
    def test_felt_percentiles_and_jitter(self):
        h = ControlHub()
        for rtt in (300, 320, 310, 330, 305):
            h.record_effect(600, 500, rtt)
        ping = h.status()["ping"]
        self.assertIsNotNone(ping["felt_p50_ms"])
        self.assertIsNotNone(ping["felt_p95_ms"])
        self.assertIsNotNone(ping["jitter_ms"])
        self.assertEqual(len(ping["samples"]), 5)
        self.assertGreaterEqual(ping["felt_p95_ms"], ping["felt_p50_ms"])

    def test_record_net_surfaces_wan(self):
        h = ControlHub()
        h.record_net(338.0, 320.0, 7)
        ping = h.status()["ping"]
        self.assertEqual(ping["wan_ms"], 338.0)
        self.assertEqual(ping["wan_min_ms"], 320.0)
        self.assertEqual(ping["retrans"], 7)

    def test_no_samples_is_safe(self):
        ping = ControlHub().status()["ping"]
        self.assertIsNone(ping["felt_p50_ms"])
        self.assertIsNone(ping["jitter_ms"])
        self.assertEqual(ping["samples"], [])


if __name__ == "__main__":
    unittest.main()
