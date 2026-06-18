"""
Constantes por versao do jogo (port de Unscrambler/Constants/Versions).

Cada patch do FFXIV troca offsets de tabela e opcodes. O perchbirdd publica
isso por patch; aqui transcrevemos a versao mais recente que temos dados
(.bin) vendorizados. Adicionar um patch novo = copiar o dicionario abaixo da
classe Constants<versao>.cs correspondente e os 6 .bin pra data/<versao>/.

Os campos *Offset/*Size so importam pra quem EXTRAI as tabelas do
ffxiv_dx11.exe (o DataGenerator do perchbirdd). Para desofuscar a partir dos
.bin ja extraidos, o que importa e: radixes/max, modo, opcodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VersionConstants:
    game_version: str
    obfuscation_enabled_mode: int

    table_radixes: tuple[int, int, int]
    table_max: tuple[int, int, int]

    init_zone_opcode: int
    unknown_obfuscation_init_opcode: int

    obfuscated_opcodes: dict[str, int] = field(default_factory=dict)

    # Em que "geracao" de KeyGenerator/Unscrambler este patch cai.
    #   "72" -> 7.2 (sem opcode key); "73" -> 7.3+ (com opcode key);
    #   "74" -> 7.4+ (seeds sairam do InitZone -> pacote inicializador).
    keygen_gen: str = "74"
    unscramble_gen: str = "73"


# --- 2026.06.10.0000.0000 (patch 7.5x) -- Constants751h1.cs ---------------
_V_2026_06_10 = VersionConstants(
    game_version="2026.06.10.0000.0000",
    obfuscation_enabled_mode=240,
    table_radixes=(107, 118, 97),
    table_max=(68, 197, 219),
    init_zone_opcode=0x8B,
    unknown_obfuscation_init_opcode=0x1D0,
    keygen_gen="74",
    unscramble_gen="73",
    obfuscated_opcodes={
        "PlayerSpawn": 0x3B4,
        "NpcSpawn": 0x113,
        "NpcSpawn2": 0xB8,
        "ActionEffect01": 0x1D9,
        "ActionEffect08": 0x141,
        "ActionEffect16": 0x191,
        "ActionEffect24": 0x231,
        "ActionEffect32": 0x38B,
        "StatusEffectList": 0x12B,
        "StatusEffectList3": 0xEF,
        "Examine": 0x1BB,
        "UpdateGearset": 0x1C4,
        "UpdateParty": 0x34C,
        "ActorControl": 0x27F,
        "ActorCast": 0x2F8,
        "UnknownEffect01": 0x213,
        "UnknownEffect16": 0x234,
        "ActionEffect02": 0x2F9,
        "ActionEffect04": 0x3A3,
    },
)


VERSIONS: dict[str, VersionConstants] = {
    _V_2026_06_10.game_version: _V_2026_06_10,
}

# Versao "mais nova" que conhecemos (default pratico).
LATEST = _V_2026_06_10.game_version


def _load_dynamic_versions():
    import json
    import os
    user_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    p = os.path.join(user_appdata, "Mitigus", "deob", "versions.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            for item in data:
                v = VersionConstants(
                    game_version=item["game_version"],
                    obfuscation_enabled_mode=item["obfuscation_enabled_mode"],
                    table_radixes=tuple(item["table_radixes"]),
                    table_max=tuple(item["table_max"]),
                    init_zone_opcode=item["init_zone_opcode"],
                    unknown_obfuscation_init_opcode=item["unknown_obfuscation_init_opcode"],
                    obfuscated_opcodes=item["obfuscated_opcodes"],
                    keygen_gen=item.get("keygen_gen", "74"),
                    unscramble_gen=item.get("unscramble_gen", "73")
                )
                VERSIONS[v.game_version] = v
                global LATEST
                if v.game_version > LATEST:
                    LATEST = v.game_version
        except Exception:
            pass


_load_dynamic_versions()


def for_game_version(game_version: str) -> VersionConstants:
    try:
        return VERSIONS[game_version]
    except KeyError as exc:
        known = ", ".join(sorted(VERSIONS)) or "(nenhuma)"
        raise ValueError(
            f"Versao de jogo nao suportada: {game_version}. "
            f"Conhecidas: {known}"
        ) from exc
