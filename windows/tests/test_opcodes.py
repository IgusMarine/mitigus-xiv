import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.protocol.opcodes import OpcodeDefinition, _parse_all, match_for_server

SAMPLE = {
    "Name": "Global.json",
    "C2S_ActionRequest": "0x00e7",
    "C2S_ActionRequestGroundTargeted": "0x00e8",
    "S2C_ActionEffect01": "0x01a6",
    "S2C_ActionEffect08": "0x0339",
    "S2C_ActionEffect16": "418",  # decimal, para testar parsing base-0 misto
    "S2C_ActionEffect24": "0x00aa",
    "S2C_ActionEffect32": "0x00bb",
    "S2C_ActorCast": "0x02b9",
    "S2C_ActorControl": "0x0273",
    "S2C_ActorControlSelf": "0x0290",
    "Common_UseOodleTcp": True,
    "Server_IpRange": "124.150.157.0/24, 153.254.80.0-153.254.80.255",
    "Server_PortRange": "55021-55040, 54994",
}


class OpcodeDefinitionTest(unittest.TestCase):
    def setUp(self):
        self.d = OpcodeDefinition.from_dict(SAMPLE)

    def test_int_parsing_hex_and_decimal(self):
        self.assertEqual(self.d.C2S_ActionRequest, 0xE7)
        self.assertEqual(self.d.S2C_ActionEffect16, 418)
        self.assertTrue(self.d.Common_UseOodleTcp)

    def test_is_action_effect(self):
        self.assertTrue(self.d.is_action_effect(0x01A6))
        self.assertTrue(self.d.is_action_effect(0x00BB))
        self.assertFalse(self.d.is_action_effect(0x00E7))  # ActionRequest não é effect

    def test_opcode_name_reverse_lookup(self):
        self.assertEqual(self.d.opcode_name(0x02B9), "S2C_ActorCast")
        self.assertEqual(self.d.opcode_name(0x0290), "S2C_ActorControlSelf")
        self.assertIsNone(self.d.opcode_name(0xDEAD))

    def test_matches_server_cidr_and_range(self):
        self.assertTrue(self.d.matches_server("124.150.157.5", 55030))  # CIDR + porta range
        self.assertTrue(self.d.matches_server("153.254.80.10", 54994))  # range a-b + porta única
        self.assertFalse(self.d.matches_server("8.8.8.8", 55030))       # ip fora
        self.assertFalse(self.d.matches_server("124.150.157.5", 443))   # porta fora

    def test_parse_all_skips_broken_entries(self):
        broken = dict(SAMPLE)
        del broken["S2C_ActionEffect32"]  # faltando um campo obrigatório
        defs = _parse_all([SAMPLE, broken])
        self.assertEqual(len(defs), 1)  # só o válido sobrevive

    def test_match_for_server(self):
        defs = [self.d]
        self.assertIs(match_for_server(defs, "124.150.157.9", 55021), self.d)
        self.assertIsNone(match_for_server(defs, "1.1.1.1", 80))


if __name__ == "__main__":
    unittest.main()
