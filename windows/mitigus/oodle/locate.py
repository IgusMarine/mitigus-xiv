"""
Localiza o ffxiv_dx11.exe automaticamente (Fase 5 — facilitar a vida do usuário).

O Oodle vem dentro do ffxiv_dx11.exe (do cliente PC). O usuário de PS5 não tem o
jogo no PC, então normalmente instala o trial gratuito do FFXIV. Em vez de obrigar
a copiar o arquivo na mão, procuramos nos lugares de instalação mais comuns
(instalador da Square Enix e bibliotecas do Steam), além de vendor\ e do caminho
explícito.
"""
from __future__ import annotations

import os
import re
from typing import List, Optional

_REL = os.path.join("game", "ffxiv_dx11.exe")

# Pastas de instalação típicas (instalador standalone / Mog Station e Steam).
_COMMON_DIRS = [
    r"C:\Program Files (x86)\SquareEnix\FINAL FANTASY XIV - A Realm Reborn",
    r"C:\Program Files (x86)\SquareEnix\FINAL FANTASY XIV Online",
    r"C:\Program Files\SquareEnix\FINAL FANTASY XIV - A Realm Reborn",
    r"C:\Program Files (x86)\Steam\steamapps\common\FINAL FANTASY XIV Online",
    r"C:\Program Files (x86)\Steam\steamapps\common\FINAL FANTASY XIV - A Realm Reborn",
]

_STEAM_GAME_DIRS = ("FINAL FANTASY XIV Online", "FINAL FANTASY XIV - A Realm Reborn")

_DEFAULT_VDFS = [
    r"C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf",
    r"C:\Program Files\Steam\steamapps\libraryfolders.vdf",
]


def steam_libraries(vdf_paths: Optional[List[str]] = None) -> List[str]:
    """Lê os caminhos de biblioteca do Steam a partir do libraryfolders.vdf."""
    libs: List[str] = []
    for vdf in vdf_paths or _DEFAULT_VDFS:
        try:
            with open(vdf, encoding="utf-8", errors="ignore") as fp:
                text = fp.read()
        except OSError:
            continue
        for m in re.finditer(r'"path"\s*"([^"]+)"', text):
            libs.append(m.group(1).replace("\\\\", "\\"))
    return libs


def candidate_paths(explicit: Optional[str] = None, base_dir: Optional[str] = None) -> List[str]:
    cands: List[str] = []
    if explicit:
        cands.append(explicit)
    if base_dir:
        cands.append(os.path.join(base_dir, "vendor", "ffxiv_dx11.exe"))
        cands.append(os.path.join(base_dir, "ffxiv_dx11.exe"))
    for d in _COMMON_DIRS:
        cands.append(os.path.join(d, _REL))
    for lib in steam_libraries():
        for game in _STEAM_GAME_DIRS:
            cands.append(os.path.join(lib, "steamapps", "common", game, _REL))
    return cands


def find_ffxiv_dx11(explicit: Optional[str] = None, base_dir: Optional[str] = None) -> Optional[str]:
    """Devolve o caminho do ffxiv_dx11.exe, ou None se não achar."""
    import sys
    our_exe = os.path.abspath(sys.executable) if getattr(sys, "frozen", False) else None
    for c in candidate_paths(explicit, base_dir):
        if c and os.path.isfile(c):
            # Ignora a si mesmo caso o executável principal esteja rodando como ffxiv_dx11.exe
            if our_exe and os.path.abspath(c) == our_exe:
                continue
            return c
    return None
