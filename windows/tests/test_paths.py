import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.paths import app_dir, is_frozen, resource_dir


class PathsTest(unittest.TestCase):
    def test_not_frozen_in_source_mode(self):
        self.assertFalse(is_frozen())

    def test_app_dir_is_engine_root(self):
        d = app_dir()
        # no modo fonte, app_dir() é a pasta windows/ (contém mitigus/ e run_proxy.py)
        self.assertTrue(os.path.isdir(os.path.join(d, "mitigus")))
        self.assertTrue(os.path.isfile(os.path.join(d, "run_proxy.py")))

    def test_resource_dir_matches_in_source_mode(self):
        self.assertEqual(resource_dir(), app_dir())


if __name__ == "__main__":
    unittest.main()
