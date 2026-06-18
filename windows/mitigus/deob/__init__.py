"""
Spike de desofuscacao de pacotes do FFXIV (uso pessoal/privado).

Port para Python da logica de perchbirdd/Unscrambler (licenca WTFPL) + a
derivacao de chave que viaja na REDE (sem injecao, sem ler memoria do jogo).
Objetivo: provar que da pra desofuscar combate (ActionEffect etc.) de um
cliente de console (PS5/PS4) com um PC no meio do trafego -- a mesma
topologia do Mitigus.

NAO e codigo de producao do Mitigus. E uma prova de conceito isolada.
Validacao byte-exata final depende de uma captura real do console.

Credito: perchbirdd (Unscrambler), NotNite (TemporalStasis).
"""

from .constants import VersionConstants, for_game_version, LATEST  # noqa: F401
from .keygen import KeyGenerator  # noqa: F401
from .unscramble import Unscrambler  # noqa: F401
from .loader import build, load_raw_tables, Deobfuscator  # noqa: F401
