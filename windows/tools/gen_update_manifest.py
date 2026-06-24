#!/usr/bin/env python3
"""
Gera os artefatos do canal de auto-update a partir das FONTES do projeto:
  - windows/update/versions.json  <- mitigus.deob.constants.VERSIONS (constantes deob)
  - windows/update/buffs.json     <- mitigus.meter.tracker.BUFFS (tabela de buffs)
  - windows/update/manifest.json  <- LATEST/__version__ + URLs + revs (hash do conteudo)

Rode antes de dar push (e antes de publicar um release):
    python tools/gen_update_manifest.py

O rev de buffs/ui e o HASH do conteudo, entao bumpa sozinho quando o arquivo muda
-> o app do usuario re-baixa so o que mudou. Trocar _BRANCH se publicar de outro.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WIN = os.path.dirname(_HERE)            # windows/
sys.path.insert(0, _WIN)

from mitigus import __version__                       # noqa: E402
from mitigus.deob.constants import VERSIONS, LATEST   # noqa: E402
from mitigus.meter.tracker import BUFFS               # noqa: E402

_REPO = "IgusMarine/mitigus-xiv"
_BRANCH = "dps-meter"
_RAW = f"https://raw.githubusercontent.com/{_REPO}/{_BRANCH}/windows"
_OUT = os.path.join(_WIN, "update")


def _short_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _write(path: str, data: bytes) -> bytes:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return data


def main() -> int:
    # versions.json (constantes deob, no formato que o loader dinamico le)
    versions = []
    for v in VERSIONS.values():
        versions.append({
            "game_version": v.game_version,
            "obfuscation_enabled_mode": v.obfuscation_enabled_mode,
            "table_radixes": list(v.table_radixes),
            "table_max": list(v.table_max),
            "init_zone_opcode": v.init_zone_opcode,
            "unknown_obfuscation_init_opcode": v.unknown_obfuscation_init_opcode,
            "obfuscated_opcodes": dict(v.obfuscated_opcodes),
            "keygen_gen": v.keygen_gen,
            "unscramble_gen": v.unscramble_gen,
        })
    _write(os.path.join(_OUT, "versions.json"),
           json.dumps(versions, indent=2).encode("utf-8"))

    # buffs.json (status_id -> def)
    buffs_bytes = _write(
        os.path.join(_OUT, "buffs.json"),
        json.dumps({str(k): val for k, val in BUFFS.items()}, indent=2).encode("utf-8"))

    # ui rev = hash do index.html publicado
    with open(os.path.join(_WIN, "mitigus", "panel", "index.html"), "rb") as f:
        ui_bytes = f.read()

    manifest = {
        "app_version": __version__,
        "app_zip_url": (f"https://github.com/{_REPO}/releases/download/"
                        f"v{__version__}/Mitigus-XIV-App.zip"),
        "deob_version": LATEST,
        "deob_constants_url": f"{_RAW}/update/versions.json",
        "deob_base_url": f"{_RAW}/mitigus/deob/data/",
        "buffs_url": f"{_RAW}/update/buffs.json",
        "buffs_rev": _short_hash(buffs_bytes),
        "ui_url": f"{_RAW}/mitigus/panel/index.html",
        "ui_rev": _short_hash(ui_bytes),
    }
    _write(os.path.join(_OUT, "manifest.json"),
           json.dumps(manifest, indent=2).encode("utf-8"))

    print("gerado em windows/update/:")
    print(f"  versions.json  ({len(versions)} versao(oes), LATEST={LATEST})")
    print(f"  buffs.json     ({len(BUFFS)} buffs, rev={manifest['buffs_rev']})")
    print(f"  manifest.json  (app v{__version__}, ui_rev={manifest['ui_rev']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
