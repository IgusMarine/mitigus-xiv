"""
Gerador de chave de desofuscacao (port de Unscrambler/Derivation/KeyGenerator).

Ponto-chave: TODAS as entradas vem da REDE + de tabelas estaticas (extraidas
offline do .exe). Nenhuma leitura de memoria do processo em runtime.

  seeds (seed1/seed2/seed3) ...... vem do pacote inicializador na rede
  table0/1/2, midtable, daytable .. estaticas (.bin por patch)
  3 chaves (Keys[0..2]) ........... derivadas por aritmetica pura (Derive)
  opcode key table ................ estatica; chave por opcode (7.3+)

KeyGenerator73 e KeyGenerator74 tem `Derive` IDENTICO no upstream; a unica
diferenca e a fonte dos seeds:
  - 7.3: seeds no InitZone (offsets 37/38/39/40)  -> generate_from_init_zone
  - 7.4+: InitZone nao tem mais; pacote inicializador dedicado (22/23/24/28)
          -> generate_from_unknown_initializer
Os dois metodos existem aqui; o chamador escolhe pela versao.
"""

from __future__ import annotations


def _i32le(buf: bytes, off: int) -> int:
    """Lê int32 com sinal, little-endian (== BitConverter.ToInt32 do C#)."""
    return int.from_bytes(buf[off:off + 4], "little", signed=True)


class KeyGenerator:
    def __init__(self, constants, raw_tables: dict[str, bytes]):
        self.constants = constants
        self.keys: list[int] = [0, 0, 0]
        self.obfuscation_enabled = False

        self._table0 = [_i32le(raw_tables["table0"], i)
                        for i in range(0, len(raw_tables["table0"]), 4)]
        self._table1 = [_i32le(raw_tables["table1"], i)
                        for i in range(0, len(raw_tables["table1"]), 4)]
        self._table2 = [_i32le(raw_tables["table2"], i)
                        for i in range(0, len(raw_tables["table2"]), 4)]
        self._midtable = raw_tables["midtable"]
        self._daytable = raw_tables["daytable"]
        # opcode key table so existe em 7.3+
        okt = raw_tables.get("opcodekeytable", b"")
        self._opcode_key_table = [_i32le(okt, i) for i in range(0, len(okt), 4)]

    # --- derivacao -------------------------------------------------------
    def _derive(self, set_idx: int, n_seed1: int, n_seed2: int, epoch: int) -> int:
        # midtable: blocos de 8 bytes; valor "byte" em +4, valor "uint32" em +0
        mid_index = 8 * (n_seed1 % (len(self._midtable) // 8))
        mid_table_value = self._midtable[4 + mid_index]
        mid_value = int.from_bytes(
            self._midtable[mid_index:mid_index + 4], "little")  # uint32

        # epoch aqui e o seed3 negado (nao um timestamp de verdade)
        epoch_days = 3 * (epoch // 60 // 60 // 24)
        day_table_index = 4 * (epoch_days % (len(self._daytable) // 4))
        day_table_value = self._daytable[day_table_index]

        set_radix = self.constants.table_radixes[set_idx]
        set_max = self.constants.table_max[set_idx]
        # precedencia C#: setRadix*(nSeed2%setMax) + (midValue*nSeed1)%setRadix
        table_index = (set_radix * (n_seed2 % set_max)
                       + (mid_value * n_seed1) % set_radix)
        table = (self._table0, self._table1, self._table2)[set_idx]
        set_result = table[table_index]

        # (byte)(...) -> low 8 bits; & 0xFF cobre overflow/sinal igual ao C#
        return (n_seed1 + mid_table_value + day_table_value + set_result) & 0xFF

    def _derive_all(self, seed1: int, seed2: int, seed3: int) -> None:
        n1 = (~seed1) & 0xFF
        n2 = (~seed2) & 0xFF
        n3 = (~seed3) & 0xFFFFFFFF
        self.keys = [self._derive(0, n1, n2, n3),
                     self._derive(1, n1, n2, n3),
                     self._derive(2, n1, n2, n3)]

    # --- fontes de seed --------------------------------------------------
    def generate_from_init_zone(self, packet: bytes) -> None:
        """7.3 e anteriores: seeds dentro do InitZone."""
        mode = packet[37]
        if mode != self.constants.obfuscation_enabled_mode:
            self.keys = [0, 0, 0]
            self.obfuscation_enabled = False
            return
        self.obfuscation_enabled = True
        seed1 = packet[38]
        seed2 = packet[39]
        seed3 = int.from_bytes(packet[40:44], "little")  # uint32
        self._derive_all(seed1, seed2, seed3)

    def generate_from_unknown_initializer(self, packet: bytes) -> None:
        """7.4+: seeds num pacote inicializador dedicado (e tambem ok em 7.3)."""
        mode = packet[22]
        if mode != self.constants.obfuscation_enabled_mode:
            self.keys = [0, 0, 0]
            self.obfuscation_enabled = False
            return
        self.obfuscation_enabled = True
        seed1 = packet[23]
        seed2 = packet[24]
        seed3 = int.from_bytes(packet[28:32], "little")  # uint32
        self._derive_all(seed1, seed2, seed3)

    # --- chave por opcode (7.3+) ----------------------------------------
    def get_opcode_based_key(self, opcode: int) -> int:
        if not self._opcode_key_table:
            raise RuntimeError("opcode key table ausente (patch < 7.3?)")
        base_key = self.keys[opcode % 3]
        idx = (opcode + base_key) % len(self._opcode_key_table)
        return self._opcode_key_table[idx]

    @property
    def opcode_key_table(self) -> list[int]:
        return self._opcode_key_table
