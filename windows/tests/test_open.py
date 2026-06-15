import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_proxy


class OpenPanelTest(unittest.TestCase):
    def test_open_app_window_returns_false_without_browser(self):
        # candidatos vazios -> não tenta lançar nada, devolve False
        self.assertFalse(run_proxy.open_app_window("http://127.0.0.1:8080", candidates=[]))

    def test_open_app_window_false_for_missing_paths(self):
        self.assertFalse(
            run_proxy.open_app_window("http://x", candidates=[r"C:\nao\existe\edge.exe"])
        )

    def test_open_panel_none_is_noop(self):
        # mode "none" não deve abrir nada nem lançar exceção
        self.assertIsNone(run_proxy._open_panel("http://127.0.0.1:8080", "none"))


if __name__ == "__main__":
    unittest.main()
