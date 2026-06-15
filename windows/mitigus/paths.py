"""
Resolução de caminhos para os dois modos: rodando do código-fonte ou empacotado
num .exe (PyInstaller, "congelado").

- `app_dir()`  : a pasta onde o app "vive" para o usuário — ao lado do .exe quando
                 empacotado, ou a pasta `windows\\` no modo fonte. É onde ficam o
                 `vendor\\` (com o ffxiv_dx11.exe) e o cache `definitions.json`.
- `resource_dir()`: onde ficam os dados embutidos (sob _MEIPASS quando congelado).
"""
from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    # mitigus/paths.py -> mitigus/ -> windows/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir() -> str:
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
