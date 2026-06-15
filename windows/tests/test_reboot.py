import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.net.adapters import _reboot_pending_decide


class RebootPendingTest(unittest.TestCase):
    def test_routing_off_never_pending(self):
        self.assertFalse(_reboot_pending_decide(False, 1000.0, 1000.0))

    def test_no_marker_not_pending(self):
        self.assertFalse(_reboot_pending_decide(True, None, 1000.0))

    def test_same_boot_session_is_pending(self):
        # marcador e boot atual iguais => não reiniciou desde a config => pendente
        self.assertTrue(_reboot_pending_decide(True, 1000.0, 1000.0))

    def test_small_drift_still_pending(self):
        # leve variação de relógio dentro da tolerância => mesma sessão
        self.assertTrue(_reboot_pending_decide(True, 1000.0, 1030.0))

    def test_different_boot_is_cleared(self):
        # boot bem diferente (reiniciou) => não pendente
        self.assertFalse(_reboot_pending_decide(True, 1000.0, 9000.0))

    def test_tolerance_boundary(self):
        self.assertTrue(_reboot_pending_decide(True, 1000.0, 1120.0, tol=120.0))
        self.assertFalse(_reboot_pending_decide(True, 1000.0, 1200.0, tol=120.0))


if __name__ == "__main__":
    unittest.main()
