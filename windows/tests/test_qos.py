import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.proxy.qos import BufferbloatController


class QosTest(unittest.TestCase):
    def test_disabled_never_drops(self):
        c = BufferbloatController()  # enabled=False por padrão
        c.update_rtt(100)
        for _ in range(10):
            c.update_rtt(1000)
        self.assertEqual(c.drop_probability(), 0.0)
        self.assertFalse(c.should_drop(1500))

    def test_stable_line_no_drop(self):
        c = BufferbloatController()
        c.set_enabled(True)
        for _ in range(20):
            c.update_rtt(120)
        self.assertEqual(c.drop_probability(), 0.0)

    def test_spike_drops_capped(self):
        c = BufferbloatController(target_excess_ms=30, max_drop=0.4)
        c.set_enabled(True)
        c.update_rtt(100)                 # baseline ~100
        for _ in range(12):
            c.update_rtt(400)             # recent dispara, baseline sobe devagar
        p = c.drop_probability()
        self.assertGreater(p, 0.0)
        self.assertLessEqual(p, 0.4)

    def test_only_big_packets_dropped(self):
        c = BufferbloatController(target_excess_ms=30, big_packet_bytes=1000,
                                  rng=lambda: 0.0)  # rng=0 -> sempre dentro da prob
        c.set_enabled(True)
        c.update_rtt(100)
        for _ in range(12):
            c.update_rtt(400)
        self.assertTrue(c.should_drop(1400))    # pacote grande de fundo: derruba
        self.assertFalse(c.should_drop(200))    # pacote pequeno (ACK/DNS): poupa

    def test_baseline_recovers_downward(self):
        c = BufferbloatController()
        c.set_enabled(True)
        for _ in range(10):
            c.update_rtt(500)
        c.update_rtt(90)                  # ping melhora -> baseline desce na hora
        for _ in range(10):
            c.update_rtt(95)
        self.assertEqual(c.drop_probability(), 0.0)  # linha lisa de novo


if __name__ == "__main__":
    unittest.main()
