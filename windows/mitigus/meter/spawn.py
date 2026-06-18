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

# "Companion Owner" no corpo do NpcSpawn/NpcSpawn2 DESOFUSCADO (perchbirdd
# Unscrambler, UnscrambleNpcSpawn offset 96; é o campo que o deob já restaura em
# unscramble.py _npc_spawn). u32 = GameObjectId do dono; 0 = NPC comum (não-pet).
OWNER_OFFSET = 96

from .names import job_abbr  # classJob -> abreviação (fonte: ClassJob.csv oficial)


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
    return name, job_abbr(cj), cj, level


def parse_npc_spawn(md: bytes) -> int:
    """Owner id (u32 LE @96) de um NpcSpawn/NpcSpawn2 DESOFUSCADO.
    0 = NPC comum (inimigo); != 0 = pet/invocação e o id é o do dono."""
    if len(md) < OWNER_OFFSET + 4:
        return 0
    return int.from_bytes(md[OWNER_OFFSET:OWNER_OFFSET + 4], "little")
