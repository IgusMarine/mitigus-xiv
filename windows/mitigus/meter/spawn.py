"""
Parser de PlayerSpawn (desofuscado) -> nome + job do ator.

Offsets no buffer que começa no HEADER IPC (PlayerSpawn já desofuscado pelo
deob: nome e Content ID vêm embaralhados e o Unscrambler os restaura):
  +610  nome do personagem (até 32 bytes, UTF-8, terminado em \\0)
  +166  level (u8)
  +167  classJob (u8)  — colado no level, no bloco de stats do personagem.
        Validado em captura real: Igus Marine -> level 166=100, job 167=37 (GNB).
        (O offset 66 testado antes dava 27 por COINCIDÊNCIA — não era o classJob.)

O id do ator vem do header do segmento (source_actor), não do corpo.
"""
from __future__ import annotations

NAME_OFFSET = 610
NAME_LEN = 32
LEVEL_OFFSET = 166
CLASSJOB_OFFSET = 167

# classJob -> abreviação de JOB (igual às chaves de cor em meter.html).
# Classes-base mapeiam pro job correspondente (cor certa em chars de nível baixo).
CLASSJOB = {
    1: "PLD", 2: "MNK", 3: "WAR", 4: "DRG", 5: "BRD", 6: "WHM", 7: "BLM",
    19: "PLD", 20: "MNK", 21: "WAR", 22: "DRG", 23: "BRD", 24: "WHM", 25: "BLM",
    26: "SMN", 27: "SMN", 28: "SCH", 29: "NIN", 30: "NIN", 31: "MCH", 32: "DRK",
    33: "AST", 34: "SAM", 35: "RDM", 36: "BLU", 37: "GNB", 38: "DNC", 39: "RPR",
    40: "SGE", 41: "VPR", 42: "PCT",
}


def parse_player_spawn(md: bytes):
    """Devolve (name, job_abbr, classjob_id, level) de um PlayerSpawn desofuscado.
    name/job podem ser None se ilegíveis."""
    if len(md) < NAME_OFFSET + NAME_LEN:
        return None
    raw = bytes(md[NAME_OFFSET:NAME_OFFSET + NAME_LEN]).split(b"\x00", 1)[0]
    try:
        name = raw.decode("utf-8") or None
    except UnicodeDecodeError:
        name = raw.decode("utf-8", "replace") or None
    cj = md[CLASSJOB_OFFSET] if len(md) > CLASSJOB_OFFSET else 0
    level = md[LEVEL_OFFSET] if len(md) > LEVEL_OFFSET else 0
    return name, CLASSJOB.get(cj), cj, level
