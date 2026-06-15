import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_proxy


class TeeTest(unittest.TestCase):
    def test_tee_writes_to_both(self):
        screen, fh = io.StringIO(), io.StringIO()
        t = run_proxy._Tee(screen, fh)
        t.write("linha de log\n")
        self.assertEqual(screen.getvalue(), "linha de log\n")
        self.assertEqual(fh.getvalue(), "linha de log\n")

    def test_tee_survives_none_stream(self):
        fh = io.StringIO()
        t = run_proxy._Tee(None, fh)
        t.write("x")
        t.flush()
        self.assertEqual(fh.getvalue(), "x")


if __name__ == "__main__":
    unittest.main()
