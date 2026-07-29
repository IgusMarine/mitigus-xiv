#!/usr/bin/env python3
"""
Espelha os dados de desofuscacao do perchbirdd/Unscrambler para este repo — o
passo que ANTES era manual a cada patch do jogo.

O que faz:
  1. lista `Unscrambler/Data/` do upstream e acha as versoes que ainda nao temos;
  2. baixa as 6 `.bin` de cada uma para `windows/mitigus/deob/data/<versao>/`;
  3. acha o `Constants*.cs` correspondente (pelo GameVersion), parseia
     radixes/max/modo/opcodes e INSERE a VersionConstants nova no
     `mitigus/deob/constants.py`, atualizando o `LATEST`.

Depois disso, `python tools/gen_update_manifest.py` + `git push` entregam a
versao nova ao app do usuario pelo canal de update (ele aplica no proximo boot).

Uso:
    python tools/sync_deob_upstream.py              # sincroniza o que falta
    python tools/sync_deob_upstream.py --check      # so diz o que falta (nao grava)

AVISO: se o upstream publicar uma GERACAO nova de algoritmo (um
`Unscrambler7X.cs` alem dos conhecidos), o script avisa — ai o port em
`mitigus/deob/unscramble.py`/`keygen.py` precisa ser revisado a mao.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_WIN = os.path.dirname(_HERE)
sys.path.insert(0, _WIN)

_API = "https://api.github.com/repos/perchbirdd/Unscrambler/contents"
_RAW = "https://raw.githubusercontent.com/perchbirdd/Unscrambler/main"
_BINS = ("table0.bin", "table1.bin", "table2.bin",
         "midtable.bin", "daytable.bin", "opcodekeytable.bin")
# geracoes de algoritmo que o nosso port cobre (unscramble.py / keygen.py)
_KNOWN_UNSCRAMBLERS = {"Unscrambler72.cs", "Unscrambler73.cs", "IUnscrambler.cs", "Versions"}
_DEFAULT_KEYGEN_GEN = "74"      # 7.4+: seeds vem no pacote inicializador
_DEFAULT_UNSCRAMBLE_GEN = "73"  # 7.3+: com opcode key

_CONSTANTS_PY = os.path.join(_WIN, "mitigus", "deob", "constants.py")
_DATA_DIR = os.path.join(_WIN, "mitigus", "deob", "data")


def _get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mitigus-xiv-sync"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_json(url: str):
    return json.loads(_get(url).decode("utf-8"))


def _vkey(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return ()


def _warn_new_algorithm() -> None:
    try:
        names = {f["name"] for f in _get_json(f"{_API}/Unscrambler/Unscramble/Versions")}
    except Exception:
        return
    novos = {n for n in names if n.endswith(".cs")} - _KNOWN_UNSCRAMBLERS
    if novos:
        print(f"  !! ATENCAO: geracao(oes) nova(s) de algoritmo no upstream: "
              f"{sorted(novos)}\n     -> revise mitigus/deob/unscramble.py e keygen.py "
              f"antes de confiar nos dados novos.")


# ---- parse do Constants<patch>.cs -----------------------------------------
def _parse_constants_cs(text: str) -> dict | None:
    def one(pattern, cast=str):
        m = re.search(pattern, text)
        return cast(m.group(1)) if m else None

    def arr(name):
        m = re.search(rf"{name}\s*=\s*\[([^\]]+)\]", text)
        if not m:
            return None
        return [int(x.strip(), 0) for x in m.group(1).split(",") if x.strip()]

    ver = one(r'GameVersion\s*=\s*"([^"]+)"')
    if not ver:
        return None
    ops = {}
    block = re.search(r"ObfuscatedOpcodes\s*=\s*new Dictionary<string,\s*int>\s*\{(.+?)\n\s*\}",
                      text, re.S)
    if block:
        for name, val in re.findall(r'\{\s*"([A-Za-z0-9_]+)"\s*,\s*(0[xX][0-9a-fA-F]+|\d+)\s*\}',
                                    block.group(1)):
            ops[name] = int(val, 0)
    return {
        "game_version": ver,
        "obfuscation_enabled_mode": one(r"ObfuscationEnabledMode\s*=\s*(\d+)", int),
        "table_radixes": arr("TableRadixes"),
        "table_max": arr("TableMax"),
        "init_zone_opcode": one(r"InitZoneOpcode\s*=\s*(0[xX][0-9a-fA-F]+|\d+)",
                                lambda s: int(s, 0)),
        "unknown_obfuscation_init_opcode": one(
            r"UnknownObfuscationInitOpcode\s*=\s*(0[xX][0-9a-fA-F]+|\d+)",
            lambda s: int(s, 0)),
        "obfuscated_opcodes": ops,
    }


def _find_constants_for(version: str) -> dict | None:
    """Procura o Constants*.cs cujo GameVersion == version (das pastas mais novas
    para as mais antigas, que e onde ele quase sempre esta)."""
    try:
        folders = [f["name"] for f in _get_json(f"{_API}/Unscrambler/Constants/Versions")
                   if f["type"] == "dir"]
    except Exception as e:
        print(f"  ! nao listei as pastas de Constants: {e}")
        return None
    for folder in sorted(folders, reverse=True):
        try:
            files = [f for f in _get_json(f"{_API}/Unscrambler/Constants/Versions/{folder}")
                     if f["name"].endswith(".cs")]
        except Exception:
            continue
        for f in sorted(files, key=lambda x: x["name"], reverse=True):
            try:
                parsed = _parse_constants_cs(_get(f["download_url"]).decode("utf-8-sig"))
            except Exception:
                continue
            if parsed and parsed["game_version"] == version:
                parsed["_source"] = f"{folder}/{f['name']}"
                return parsed
    return None


# ---- escrita no constants.py ---------------------------------------------
def _render_block(c: dict, slug: str) -> str:
    ops = "\n".join(f'        "{k}": 0x{v:X},' for k, v in c["obfuscated_opcodes"].items())
    return (
        f'# --- {c["game_version"]} -- {c["_source"]} (via tools/sync_deob_upstream.py)\n'
        f"{slug} = VersionConstants(\n"
        f'    game_version="{c["game_version"]}",\n'
        f'    obfuscation_enabled_mode={c["obfuscation_enabled_mode"]},\n'
        f'    table_radixes={tuple(c["table_radixes"])},\n'
        f'    table_max={tuple(c["table_max"])},\n'
        f'    init_zone_opcode=0x{c["init_zone_opcode"]:X},\n'
        f'    unknown_obfuscation_init_opcode=0x{c["unknown_obfuscation_init_opcode"]:X},\n'
        f'    keygen_gen="{_DEFAULT_KEYGEN_GEN}",\n'
        f'    unscramble_gen="{_DEFAULT_UNSCRAMBLE_GEN}",\n'
        f"    obfuscated_opcodes={{\n{ops}\n    }},\n"
        f")\n"
    )


def _inject(constants_src: str, c: dict) -> tuple[str, str]:
    slug = "_V_" + c["game_version"].replace(".", "_")
    if slug in constants_src:
        return constants_src, slug
    nl = "\r\n" if "\r\n" in constants_src else "\n"
    src = constants_src.replace("\r\n", "\n")
    anchor = "VERSIONS: dict[str, VersionConstants] = {"
    if anchor not in src:
        raise RuntimeError("nao achei o dict VERSIONS no constants.py")
    block = _render_block(c, slug)
    src = src.replace(anchor, block + "\n\n" + anchor, 1)
    # registra no dict, logo depois da abertura
    src = src.replace(anchor, anchor + f"\n    {slug}.game_version: {slug},", 1)
    # LATEST = a versao mais nova conhecida
    src = re.sub(r"^LATEST = _V_[0-9_]+\.game_version",
                 f"LATEST = {slug}.game_version", src, count=1, flags=re.M)
    return src.replace("\n", nl) if nl == "\r\n" else src, slug


def _download_bins(version: str) -> bool:
    dest = os.path.join(_DATA_DIR, version)
    if all(os.path.exists(os.path.join(dest, b)) for b in _BINS):
        return False
    tmp = dest + ".part"
    os.makedirs(tmp, exist_ok=True)
    for b in _BINS:
        data = _get(f"{_RAW}/Unscrambler/Data/{version}/{b}")
        with open(os.path.join(tmp, b), "wb") as f:
            f.write(data)
        print(f"    {b} ({len(data)} bytes)")
    if os.path.isdir(dest):
        import shutil
        shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)
    return True


def main() -> int:
    p = argparse.ArgumentParser(description="Espelha dados do deob do perchbirdd")
    p.add_argument("--check", action="store_true", help="so mostra o que falta")
    p.add_argument("--all", action="store_true",
                   help="tambem traz builds ANTERIORES ao nosso LATEST (historico; "
                        "normalmente inutil — o jogo so anda pra frente)")
    args = p.parse_args()

    from mitigus.deob.constants import LATEST, VERSIONS  # depois do sys.path
    have = set(VERSIONS)
    print(f"versoes que temos: {', '.join(sorted(have)) or '(nenhuma)'}  (LATEST={LATEST})")

    try:
        upstream = [f["name"] for f in _get_json(f"{_API}/Unscrambler/Data")
                    if f["type"] == "dir"]
    except Exception as e:
        print(f"! nao consegui listar o upstream: {e}")
        return 1
    missing = sorted((set(upstream) - have), key=_vkey)
    if not args.all:  # so o que e mais novo que o nosso LATEST (o caso real)
        missing = [v for v in missing if _vkey(v) > _vkey(LATEST)]
    if not missing:
        print("nada novo no upstream — tudo em dia.")
        return 0
    print(f"faltando: {', '.join(missing)}")
    _warn_new_algorithm()
    if args.check:
        return 0

    with open(_CONSTANTS_PY, encoding="utf-8") as f:
        src = f.read()
    added = []
    for ver in missing:
        print(f"\n> {ver}")
        c = _find_constants_for(ver)
        if not c:
            print("  ! sem Constants*.cs correspondente no upstream; pulando "
                  "(as .bin sem as constantes nao servem)")
            continue
        if not (c["table_radixes"] and c["table_max"] and c["obfuscated_opcodes"]
                and c["obfuscation_enabled_mode"] is not None
                and c["unknown_obfuscation_init_opcode"] is not None):
            print(f"  ! {c['_source']} incompleto p/ parse automatico; pulando")
            continue
        print(f"  constantes: {c['_source']} ({len(c['obfuscated_opcodes'])} opcodes)")
        _download_bins(ver)
        src, slug = _inject(src, c)
        added.append((ver, slug))

    if not added:
        print("\nnada aplicado.")
        return 1
    with open(_CONSTANTS_PY, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print(f"\nconstants.py atualizado: {', '.join(v for v, _ in added)}")
    print("proximos passos:")
    print("  1) python -m unittest discover -s tests      (round-trips do deob)")
    print("  2) python tools/gen_update_manifest.py")
    print("  3) git add -A && git commit && git push      (o app do usuario pega sozinho)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
