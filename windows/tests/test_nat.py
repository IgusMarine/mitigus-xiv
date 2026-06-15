import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.proxy.masquerade import NatTable


class NatTableTest(unittest.TestCase):
    def test_snat_allocates_and_reuses(self):
        t = NatTable(pool=(20000, 20009))
        a = t.snat("tcp", "192.168.0.50", 5000, "8.8.8.8", 443)
        self.assertTrue(20000 <= a <= 20009)
        # mesmo fluxo -> mesma porta
        self.assertEqual(t.snat("tcp", "192.168.0.50", 5000, "8.8.8.8", 443), a)
        # fluxo diferente -> porta diferente
        b = t.snat("tcp", "192.168.0.50", 5001, "8.8.8.8", 443)
        self.assertNotEqual(a, b)

    def test_dnat_reverses_the_mapping(self):
        t = NatTable(pool=(20000, 20009))
        a = t.snat("udp", "192.168.0.50", 5300, "1.1.1.1", 53)
        # resposta volta de 1.1.1.1:53 para PC:a
        self.assertEqual(t.dnat("udp", a, "1.1.1.1", 53), ("192.168.0.50", 5300))
        # NAT cone (full cone): o retorno volta de QUALQUER origem pra (proto, alloc)
        # -> é isso que faz jogo online/STUN funcionar (NAT Tipo 2).
        self.assertEqual(t.dnat("udp", a, "9.9.9.9", 53), ("192.168.0.50", 5300))
        # protocolo que não casa, ou porta não alocada -> None
        self.assertIsNone(t.dnat("tcp", a, "1.1.1.1", 53))
        self.assertIsNone(t.dnat("udp", 29999, "1.1.1.1", 53))

    def test_cone_mapping_same_external_port_across_destinations(self):
        # O CORAÇÃO do fix: o mesmo socket do aparelho (9308) usa a MESMA porta
        # externa pra destinos DIFERENTES (STUN + servidor de jogo). NAT simétrico
        # dava portas diferentes (Tipo 3, quebrava jogos); cone dá a mesma (Tipo 2).
        t = NatTable(pool=(20000, 20009))
        a = t.snat("udp", "192.168.0.50", 9308, "52.40.62.108", 3478)   # STUN
        b = t.snat("udp", "192.168.0.50", 9308, "45.180.149.182", 12329)  # jogo
        self.assertEqual(a, b)

    def test_pool_exhaustion_returns_none(self):
        t = NatTable(pool=(20000, 20001))  # só 2 portas
        self.assertIsNotNone(t.snat("tcp", "10.0.0.2", 1, "8.8.8.8", 443))
        self.assertIsNotNone(t.snat("tcp", "10.0.0.2", 2, "8.8.8.8", 443))
        self.assertIsNone(t.snat("tcp", "10.0.0.2", 3, "8.8.8.8", 443))

    def test_gc_frees_ports(self):
        clock = [0.0]
        t = NatTable(pool=(20000, 20000), ttl=10.0, clock=lambda: clock[0])  # 1 porta só
        a = t.snat("tcp", "10.0.0.2", 1, "8.8.8.8", 443)
        self.assertIsNotNone(a)
        self.assertIsNone(t.snat("tcp", "10.0.0.2", 2, "8.8.8.8", 443))  # cheia
        clock[0] = 100.0
        self.assertEqual(t.gc(), 1)  # expira a antiga
        self.assertIsNotNone(t.snat("tcp", "10.0.0.2", 2, "8.8.8.8", 443))  # porta liberada


if __name__ == "__main__":
    unittest.main()
