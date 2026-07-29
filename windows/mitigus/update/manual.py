"""
Aplicacao MANUAL de opcodes — autonomia pro usuario num patch-day, sem esperar
por um release nosso.

Aceita o que a comunidade publica, em 3 formatos, e detecta sozinho qual e:

  1. WEAVE (definicoes estilo XivAlexander): JSON com `S2C_ActionEffect01` /
     `C2S_ActionRequest`. Objeto unico ou lista. -> grava em
     `<pasta do app>\\opcodes-manual.json`, que tem PRECEDENCIA sobre o cache
     baixado (e nao e sobrescrito pelo auto-update). Vale JA (o relay recarrega).

  2. DEOB/meter (constantes estilo perchbirdd) em JSON: objeto/lista com
     `game_version` + `obfuscated_opcodes`. -> mescla em
     `%LOCALAPPDATA%\\Mitigus\\deob\\versions.json`.

  3. DEOB/meter em C# (o proprio `Constants<patch>.cs` do perchbirdd, colado
     inteiro). -> parseado e tratado como (2).

Nos casos 2/3 as TABELAS (.bin) tambem sao necessarias; se faltarem, tentamos
baixar do perchbirdd (best-effort) e avisamos se nao der. O meter passa a valer
no PROXIMO boot (o desofuscador e montado na inicializacao).

Tudo devolve um dict {"ok", "kind", "detail", "restart"} pro painel mostrar.
"""
from __future__ import annotations

import json
import os
import re

from ..paths import app_dir

_WEAVE_KEYS = ("S2C_ActionEffect01", "C2S_ActionRequest", "S2C_ActorControl")
_DEOB_BINS = ("table0.bin", "table1.bin", "table2.bin",
              "midtable.bin", "daytable.bin", "opcodekeytable.bin")
_UPSTREAM_DATA = ("https://raw.githubusercontent.com/perchbirdd/Unscrambler/"
                  "main/Unscrambler/Data")


def manual_weave_path() -> str:
    """Definicoes de weave aplicadas a mao (tem precedencia sobre o cache)."""
    return os.path.join(app_dir(), "opcodes-manual.json")


def _deob_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Mitigus", "deob")


# ---- parse do Constants<patch>.cs (formato do perchbirdd) -------------------
def parse_constants_cs(text: str):
    """Extrai uma VersionConstants (dict) de um Constants<patch>.cs. None se nao
    parecer com um. Compartilhado com tools/sync_deob_upstream.py."""
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
        for name, val in re.findall(
                r'\{\s*"([A-Za-z0-9_]+)"\s*,\s*(0[xX][0-9a-fA-F]+|\d+)\s*\}', block.group(1)):
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
        "keygen_gen": "74",
        "unscramble_gen": "73",
    }


# ---- validacao -------------------------------------------------------------
def _is_weave(obj) -> bool:
    return isinstance(obj, dict) and any(k in obj for k in _WEAVE_KEYS)


def _is_deob(obj) -> bool:
    return (isinstance(obj, dict) and "game_version" in obj
            and "obfuscated_opcodes" in obj)


_DEOB_REQUIRED = ("game_version", "obfuscation_enabled_mode", "table_radixes",
                  "table_max", "unknown_obfuscation_init_opcode", "obfuscated_opcodes")


def _deob_missing(entry: dict) -> list:
    return [k for k in _DEOB_REQUIRED if entry.get(k) in (None, "", [], {})]


# ---- aplicacao -------------------------------------------------------------
def apply_manual(text: str, log=lambda m: None) -> dict:
    """Aplica o conteudo colado/soltado pelo usuario. Nunca levanta."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "detail": "nada para aplicar (conteudo vazio)"}

    obj = None
    try:
        obj = json.loads(text)
    except ValueError:
        parsed = parse_constants_cs(text)   # talvez seja o .cs do perchbirdd
        if parsed is None:
            return {"ok": False, "detail": "não reconheci o formato: não é JSON "
                                           "válido nem um Constants<patch>.cs"}
        obj = parsed

    items = obj if isinstance(obj, list) else [obj]
    if not items:
        return {"ok": False, "detail": "lista vazia"}

    if all(_is_weave(i) for i in items):
        return _apply_weave(items, log)
    if all(_is_deob(i) for i in items):
        return _apply_deob(items, log)
    return {"ok": False, "detail": "conteúdo não parece definição de opcodes "
                                   "(weave: S2C_ActionEffect01…; deob: game_version "
                                   "+ obfuscated_opcodes)"}


def _apply_weave(items, log) -> dict:
    from ..protocol.opcodes import OpcodeDefinition
    ok = []
    for i, raw in enumerate(items):
        entry = dict(raw)
        entry.setdefault("Name", f"manual-{i}")
        try:
            OpcodeDefinition.from_dict(entry)   # valida ANTES de gravar
        except (KeyError, ValueError, TypeError) as e:
            return {"ok": False, "kind": "weave",
                    "detail": f"definição inválida ({entry.get('Name')}): {e}"}
        ok.append(entry)
    path = manual_weave_path()
    tmp = path + ".part"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ok, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        return {"ok": False, "kind": "weave", "detail": f"não consegui gravar: {e}"}
    log(f"opcodes manuais (weave) aplicados: {len(ok)} definição(ões)")
    return {"ok": True, "kind": "weave", "count": len(ok), "restart": False,
            "detail": f"{len(ok)} definição(ões) de weave aplicada(s) — valendo agora"}


def _apply_deob(items, log) -> dict:
    entries, missing_bins = [], []
    for raw in items:
        miss = _deob_missing(raw)
        if miss:
            return {"ok": False, "kind": "deob",
                    "detail": f"faltam campos em {raw.get('game_version','?')}: "
                              f"{', '.join(miss)}"}
        e = dict(raw)
        e.setdefault("keygen_gen", "74")
        e.setdefault("unscramble_gen", "73")
        entries.append(e)

    deob = _deob_dir()
    try:
        os.makedirs(deob, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "kind": "deob", "detail": f"não consegui criar {deob}: {exc}"}

    # mescla com o que ja existe (por game_version)
    path = os.path.join(deob, "versions.json")
    merged = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                for it in json.load(f):
                    merged[it["game_version"]] = it
        except Exception:
            merged = {}
    for e in entries:
        merged[e["game_version"]] = e
    tmp = path + ".part"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(merged.values()), f, indent=2)
        os.replace(tmp, path)
    except OSError as exc:
        return {"ok": False, "kind": "deob", "detail": f"não consegui gravar: {exc}"}

    for e in entries:
        if not _ensure_bins(e["game_version"], deob, log):
            missing_bins.append(e["game_version"])

    vers = ", ".join(e["game_version"] for e in entries)
    if missing_bins:
        return {"ok": True, "kind": "deob", "restart": True, "bins_missing": missing_bins,
                "detail": f"opcodes de {vers} salvos, mas faltam as tabelas (.bin) e não "
                          f"consegui baixar. O weave funciona; o medidor de DPS só volta "
                          f"com as tabelas."}
    log(f"opcodes manuais (deob) aplicados: {vers}")
    return {"ok": True, "kind": "deob", "restart": True,
            "detail": f"opcodes+tabelas de {vers} aplicados — reabra o Mitigus para o "
                      f"medidor de DPS usar"}


def _ensure_bins(version: str, deob_dir: str, log) -> bool:
    """Garante as 6 .bin da versao; tenta baixar do perchbirdd se faltarem."""
    dest = os.path.join(deob_dir, "data", version)
    if all(os.path.exists(os.path.join(dest, b)) for b in _DEOB_BINS):
        return True
    try:
        from .updater import _http_get
        tmp = dest + ".part"
        os.makedirs(tmp, exist_ok=True)
        for b in _DEOB_BINS:
            data = _http_get(f"{_UPSTREAM_DATA}/{version}/{b}", timeout=120)
            with open(os.path.join(tmp, b), "wb") as f:
                f.write(data)
        if os.path.isdir(dest):
            import shutil
            shutil.rmtree(dest, ignore_errors=True)
        os.replace(tmp, dest)
        log(f"tabelas de {version} baixadas do perchbirdd")
        return True
    except Exception as e:
        log(f"não consegui baixar as tabelas de {version}: {e}")
        return False


# ---- pasta de arrastar-e-soltar -------------------------------------------
def drop_dir() -> str:
    return os.path.join(app_dir(), "opcodes")


def apply_drop_folder(log=lambda m: None) -> list:
    """Aplica os arquivos que o usuario soltou em `<pasta do app>\\opcodes\\`
    (.json ou .cs). Cada arquivo aplicado ganha o sufixo `.aplicado` para nao
    repetir no proximo boot. Devolve a lista de resultados."""
    d = drop_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if not name.lower().endswith((".json", ".cs", ".txt")):
            continue
        full = os.path.join(d, name)
        try:
            with open(full, encoding="utf-8-sig") as f:
                text = f.read()
        except OSError as e:
            log(f"opcodes/{name}: não consegui ler ({e})")
            continue
        res = apply_manual(text, log)
        res["file"] = name
        out.append(res)
        log(f"opcodes/{name}: {res.get('detail')}")
        if res.get("ok"):
            try:
                os.replace(full, full + ".aplicado")
            except OSError:
                pass
    return out
