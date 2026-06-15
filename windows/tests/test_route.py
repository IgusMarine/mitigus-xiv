import os
import socket
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.net.socks5 import build_connect_request
from mitigus.panel.hub import ControlHub


class Socks5Test(unittest.TestCase):
    def test_ipv4_request(self):
        req = build_connect_request("8.8.8.8", 443)
        self.assertEqual(req[:4], b"\x05\x01\x00\x01")          # ver/cmd/rsv/atyp=ipv4
        self.assertEqual(req[4:8], socket.inet_aton("8.8.8.8"))
        self.assertEqual(req[8:], struct.pack("!H", 443))

    def test_domain_request(self):
        req = build_connect_request("vps.exemplo.com", 1080)
        self.assertEqual(req[:4], b"\x05\x01\x00\x03")          # atyp=domínio
        self.assertEqual(req[4], len(b"vps.exemplo.com"))
        self.assertEqual(req[5:5 + req[4]], b"vps.exemplo.com")
        self.assertEqual(req[-2:], struct.pack("!H", 1080))


class HubRouteTest(unittest.TestCase):
    def test_default_off(self):
        self.assertEqual(ControlHub().route()["mode"], "off")

    def test_set_and_clear(self):
        h = ControlHub()
        r = h.set_route(mode="socks5", host=" 1.2.3.4 ", port="1080")
        self.assertEqual(r["mode"], "socks5")
        self.assertEqual(r["host"], "1.2.3.4")   # trim
        self.assertEqual(r["port"], 1080)         # int
        self.assertEqual(h.status()["route"]["mode"], "socks5")
        self.assertEqual(h.set_route(mode="off")["mode"], "off")

    def test_bad_port_ignored(self):
        h = ControlHub()
        h.set_route(mode="socks5", host="x", port="abc")
        self.assertEqual(h.route()["port"], 1080)  # mantém default


if __name__ == "__main__":
    unittest.main()
