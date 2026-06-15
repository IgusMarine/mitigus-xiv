import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IS_X64 = sys.maxsize > 2**32
KERNEL32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "kernel32.dll")


@unittest.skipUnless(IS_X64, "PeImage é x64-only")
@unittest.skipUnless(os.path.isfile(KERNEL32), "kernel32.dll não encontrado")
class PeImageTest(unittest.TestCase):
    """Valida o mapeador PE manual contra uma DLL real do sistema (sem precisar do jogo)."""

    @classmethod
    def setUpClass(cls):
        from mitigus.oodle.pe import PeImage

        with open(KERNEL32, "rb") as fp:
            cls.img = PeImage(fp.read())

    def test_headers(self):
        self.assertEqual(self.img.dos.e_magic, 0x5A4D)         # 'MZ'
        self.assertEqual(self.img.nt.Signature, 0x4550)        # 'PE\0\0'
        self.assertEqual(self.img.nt.OptionalHeader.Magic, 0x20B)  # PE32+

    def test_mapped_and_has_text(self):
        self.assertTrue(self.img.address and self.img.address.value)  # VirtualAlloc ok + relocate rodou
        text = self.img.section_header(b".text")
        self.assertGreater(text.VirtualAddress, 0)
        self.assertGreater(text.VirtualSize, 0)
        view = self.img.section(b".text")
        self.assertEqual(len(view), text.VirtualSize)

    def test_resolve_rip_relative(self):
        text = self.img.section_header(b".text")
        addr = text.VirtualAddress  # escreve num ponto da nossa cópia privada
        for rel in (0x10, -0x20, 0x0):
            self.img.view[addr] = 0xE8
            self.img.view[addr + 1 : addr + 5] = (rel & 0xFFFFFFFF).to_bytes(4, "little")
            self.assertEqual(self.img.resolve_rip_relative(addr), addr + 5 + rel)

    def test_section_header_missing_raises(self):
        with self.assertRaises(KeyError):
            self.img.section_header(b".nope")


if __name__ == "__main__":
    unittest.main()
