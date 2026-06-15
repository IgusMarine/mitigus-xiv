import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.proxy.conntrack import ConnTrack


class ConnTrackTest(unittest.TestCase):
    def test_remember_lookup_forget(self):
        ct = ConnTrack()
        self.assertIsNone(ct.lookup("1.1.1.1", 5))
        ct.remember("1.1.1.1", 5, "2.2.2.2", 80)
        self.assertEqual(ct.lookup("1.1.1.1", 5), ("2.2.2.2", 80))
        self.assertEqual(len(ct), 1)
        ct.forget("1.1.1.1", 5)
        self.assertIsNone(ct.lookup("1.1.1.1", 5))

    def test_gc_expires_stale_entries(self):
        clock = [0.0]
        ct = ConnTrack(ttl=10.0, clock=lambda: clock[0])
        ct.remember("a", 1, "b", 2)
        clock[0] = 5.0
        self.assertEqual(ct.lookup("a", 1), ("b", 2))  # refresca last_seen p/ 5
        clock[0] = 20.0                                 # 15s desde o refresh > ttl
        self.assertEqual(ct.gc(), 1)
        self.assertIsNone(ct.lookup("a", 1))
        self.assertEqual(len(ct), 0)

    def test_gc_keeps_fresh(self):
        clock = [0.0]
        ct = ConnTrack(ttl=10.0, clock=lambda: clock[0])
        ct.remember("a", 1, "b", 2)
        clock[0] = 3.0
        self.assertEqual(ct.gc(), 0)
        self.assertEqual(ct.lookup("a", 1), ("b", 2))


if __name__ == "__main__":
    unittest.main()
