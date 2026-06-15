import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_tap import _Conn, _Reasm


class ReasmTest(unittest.TestCase):
    def test_in_order(self):
        r = _Reasm()
        r.set_isn(100)  # dados começam em 101 (após o SYN)
        self.assertEqual(r.push(101, b"AB"), b"AB")
        self.assertEqual(r.push(103, b"CD"), b"CD")

    def test_without_isn_yields_nothing(self):
        r = _Reasm()
        self.assertEqual(r.push(500, b"XYZ"), b"")  # não vimos o SYN -> não decodifica

    def test_out_of_order_buffers_then_drains(self):
        r = _Reasm()
        r.set_isn(100)
        self.assertEqual(r.push(103, b"CD"), b"")        # futuro: bufferiza
        self.assertEqual(r.push(101, b"AB"), b"ABCD")    # chega o anterior e drena

    def test_full_retransmit_is_ignored(self):
        r = _Reasm()
        r.set_isn(100)
        self.assertEqual(r.push(101, b"AB"), b"AB")
        self.assertEqual(r.push(101, b"AB"), b"")        # duplicata: nada novo

    def test_partial_overlap_emits_only_new_bytes(self):
        r = _Reasm()
        r.set_isn(100)
        self.assertEqual(r.push(101, b"ABCD"), b"ABCD")
        self.assertEqual(r.push(103, b"CDEF"), b"EF")    # só os bytes inéditos

    def test_seq_wraparound(self):
        r = _Reasm()
        r.set_isn(0xFFFFFFFE)            # próximo = 0xFFFFFFFF
        self.assertEqual(r.push(0xFFFFFFFF, b"AB"), b"AB")   # next vira 1 (wrap)
        self.assertEqual(r.push(1, b"CD"), b"CD")


class ConnTest(unittest.TestCase):
    def test_begin_enables_dry_run(self):
        class _FakeMit:
            dry_run = False

        fake = _FakeMit()
        logs = []
        conn = _Conn(lambda c, s: fake, ("10.0.0.2", 5000), ("1.2.3.4", 54992), logs.append)
        conn.begin()
        self.assertIs(conn.mit, fake)
        self.assertTrue(fake.dry_run)  # tap força read-only

    def test_begin_handles_no_opcodes(self):
        logs = []
        conn = _Conn(lambda c, s: None, ("10.0.0.2", 5000), ("1.2.3.4", 54992), logs.append)
        conn.begin()
        self.assertIsNone(conn.mit)
        self.assertTrue(any("passthrough" in m for m in logs))


if __name__ == "__main__":
    unittest.main()
