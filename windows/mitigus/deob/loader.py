"""
Carregador das tabelas .bin + fachada Deobfuscator.

Os .bin ficam em data/<game_version>/ (vendorizados do perchbirdd/Unscrambler,
licenca WTFPL). Para um patch novo: copie os 6 .bin pra data/<versao>/ e
adicione a versao em constants.py.
"""

from __future__ import annotations

import os

from .constants import for_game_version, LATEST
from .keygen import KeyGenerator
from .unscramble import Unscrambler, opcode_at_ipc_start

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# nomes esperados; opcodekeytable so existe em 7.3+
_TABLE_FILES = {
    "table0": "table0.bin",
    "table1": "table1.bin",
    "table2": "table2.bin",
    "midtable": "midtable.bin",
    "daytable": "daytable.bin",
    "opcodekeytable": "opcodekeytable.bin",
}


def load_raw_tables(game_version: str) -> dict[str, bytes]:
    base = os.path.join(_DATA_DIR, game_version)
    if not os.path.isdir(base):
        raise FileNotFoundError(
            f"Sem dados .bin para {game_version} em {base}. "
            f"Copie os .bin do repo perchbirdd/Unscrambler."
        )
    out: dict[str, bytes] = {}
    for key, fname in _TABLE_FILES.items():
        path = os.path.join(base, fname)
        if os.path.exists(path):
            with open(path, "rb") as fh:
                out[key] = fh.read()
        elif key == "opcodekeytable":
            out[key] = b""  # patch < 7.3
        else:
            raise FileNotFoundError(f"Tabela obrigatoria ausente: {path}")
    return out


def build(game_version: str = LATEST):
    """Retorna (constants, key_generator, unscrambler) prontos."""
    constants = for_game_version(game_version)
    raw = load_raw_tables(game_version)
    keygen = KeyGenerator(constants, raw)
    unscrambler = Unscrambler(constants)
    return constants, keygen, unscrambler


class Deobfuscator:
    """
    Fachada de alto nivel para o relay.

    Uso tipico:
        deob = Deobfuscator()                 # usa o patch mais novo
        deob.feed_initializer(init_pkt)       # 1x por sessao (do servidor)
        clean = deob.unscramble_copy(ipc_buf) # por pacote IPC (read-only)
    """

    def __init__(self, game_version: str = LATEST):
        self.game_version = game_version
        self.constants, self.keygen, self.unscrambler = build(game_version)

    @property
    def is_active(self) -> bool:
        return self.keygen.obfuscation_enabled

    def feed_initializer(self, packet: bytes) -> bool:
        """
        Alimenta o pacote inicializador (do servidor) que carrega os seeds.
        Retorna True se a ofuscacao esta ligada nesta sessao.
        """
        if self.constants.keygen_gen == "74":
            self.keygen.generate_from_unknown_initializer(packet)
        else:
            self.keygen.generate_from_init_zone(packet)
        return self.keygen.obfuscation_enabled

    def feed_keys(self, key0: int, key1: int, key2: int) -> None:
        """Atalho p/ injetar as 3 chaves direto (ex.: vindas de outra fonte)."""
        self.keygen.keys = [key0 & 0xFF, key1 & 0xFF, key2 & 0xFF]
        self.keygen.obfuscation_enabled = any(self.keygen.keys)

    def unscramble_copy(self, ipc_buf: bytes) -> bytearray:
        """
        Desofusca uma COPIA e devolve. NAO altera o buffer original
        (que deve seguir intacto pro console).
        """
        buf = bytearray(ipc_buf)
        k = self.keygen.keys
        self.unscrambler.unscramble(buf, k[0], k[1], k[2], self.keygen.opcode_key_table)
        return buf

    def opcode_of(self, ipc_buf: bytes) -> int:
        return opcode_at_ipc_start(ipc_buf)
