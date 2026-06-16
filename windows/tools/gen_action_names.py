#!/usr/bin/env python3
"""
Gera o mapa id->nome de ações e id->job a partir do ffxiv-datamining OFICIAL.

Baixa Action.csv + ClassJob.csv (xivapi/ffxiv-datamining), filtra só as ações
de COMBATE e grava um JSON enxuto em mitigus/meter/data/actions.json — que o
meter usa pra mostrar "Solid Barrel" em vez de #16145.

IMPORTANTE (licença): os DADOS são propriedade da Square Enix (o repo de
datamining não tem licença de redistribuição). Por isso o JSON gerado é
**gitignored** — não vai pro repo público. Cada um gera o seu localmente:

    python tools/gen_action_names.py

Crédito: dados de github.com/xivapi/ffxiv-datamining (Square Enix).
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import urllib.request

ROOT = "https://raw.githubusercontent.com/xivapi/ffxiv-datamining/master"
# o layout do repo variou entre patches: tenta csv/en/ e depois csv/
PREFIXES = ("csv/en", "csv")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(HERE), "mitigus", "meter", "data")
OUT = os.path.join(OUT_DIR, "actions.json")

# ActionCategory que contam como ações de combate (auto/spell/weaponskill/ability
# + limit break). Fonte: csv/ActionCategory.csv.
COMBAT_CATEGORIES = {1, 2, 3, 4, 9, 15}


def _fetch(name: str) -> str:
    last = None
    for prefix in PREFIXES:
        url = f"{ROOT}/{prefix}/{name}"
        print(f"  baixando {url} ...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mitigus-xiv"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code != 404:
                raise
    raise last


def _rows(text: str):
    return list(csv.reader(io.StringIO(text)))


def build_actions(text: str) -> dict:
    rows = _rows(text)
    header = rows[0]  # linha 0 = nomes de coluna; dados a partir da linha 1
    i_name = header.index("Name")
    i_cat = header.index("ActionCategory")
    out = {}
    for row in rows[1:]:
        if not row or not row[0].isdigit():
            continue
        try:
            cat = int(row[i_cat])
        except ValueError:
            continue
        name = row[i_name].strip()
        if name and cat in COMBAT_CATEGORIES:
            out[int(row[0])] = name
    return out


def build_jobs(text: str) -> dict:
    rows = _rows(text)
    header = rows[0]
    i_abbr = header.index("Abbreviation")
    out = {}
    for row in rows[1:]:
        if not row or not row[0].isdigit():
            continue
        abbr = row[i_abbr].strip()
        if abbr:
            out[int(row[0])] = abbr
    return out


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    actions = build_actions(_fetch("Action.csv"))
    jobs = build_jobs(_fetch("ClassJob.csv"))
    data = {"_meta": "ffxiv-datamining (Square Enix); gerado por tools/gen_action_names.py",
            "actions": actions, "jobs": jobs}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT)
    print(f"  OK: {len(actions)} ações + {len(jobs)} jobs -> {OUT} ({size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
