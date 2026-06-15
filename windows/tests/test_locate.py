import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.oodle.locate import find_ffxiv_dx11, steam_libraries


class LocateTest(unittest.TestCase):
    def test_explicit_path_used(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ffxiv_dx11.exe")
            open(p, "wb").close()
            self.assertEqual(find_ffxiv_dx11(explicit=p), p)

    def test_vendor_under_base_dir(self):
        with tempfile.TemporaryDirectory() as d:
            vendor = os.path.join(d, "vendor")
            os.makedirs(vendor)
            p = os.path.join(vendor, "ffxiv_dx11.exe")
            open(p, "wb").close()
            self.assertEqual(find_ffxiv_dx11(base_dir=d), p)

    def test_steam_libraries_parsed_from_vdf(self):
        with tempfile.TemporaryDirectory() as d:
            vdf = os.path.join(d, "libraryfolders.vdf")
            with open(vdf, "w", encoding="utf-8") as f:
                f.write('"libraryfolders"\n{\n  "0"\n  {\n    "path"  "D:\\\\Games\\\\Steam"\n  }\n}\n')
            libs = steam_libraries([vdf])
            self.assertIn("D:\\Games\\Steam", libs)


if __name__ == "__main__":
    unittest.main()
