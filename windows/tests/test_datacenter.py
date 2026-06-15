import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.net.datacenter import lookup


class DatacenterTest(unittest.TestCase):
    def test_na(self):
        self.assertEqual(lookup("204.2.29.6")["region"], "NA")
        self.assertEqual(lookup("204.2.229.9")["region"], "NA")

    def test_eu_jp_oce(self):
        self.assertEqual(lookup("80.239.145.1")["region"], "EU")
        self.assertEqual(lookup("124.150.157.5")["region"], "JP")
        self.assertEqual(lookup("103.6.20.2")["region"], "OCE")

    def test_unknown_and_none(self):
        self.assertIsNone(lookup("1.2.3.4")["region"])
        self.assertIsNone(lookup(None)["region"])

    def test_has_label(self):
        self.assertEqual(lookup("204.2.29.6")["label"], "América do Norte")


if __name__ == "__main__":
    unittest.main()
