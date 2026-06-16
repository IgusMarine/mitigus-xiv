"""
Lookup de NOME de ação e abreviação de JOB, a partir de dados OFICIAIS do FFXIV.

Os dados vêm de `data/actions.json`, gerado por `tools/gen_action_names.py`
(fonte: xivapi/ffxiv-datamining, conteúdo da Square Enix). Esse arquivo é
GITIGNORED — não vai pro repo público; cada um gera o seu. Se ele não existir,
`action_name` cai pra "#<id>" e `job_abbr` usa o mapa estático abaixo (o id de
job ainda sai certo, só sem o arquivo de ações).
"""
from __future__ import annotations

import functools
import json
import os

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "actions.json")

# Mapa estático de fallback (csv/ClassJob.csv). Jobs 19-43 + classes-base 1-7.
_JOBS = {
    1: "GLA", 2: "PGL", 3: "MRD", 4: "LNC", 5: "ARC", 6: "CNJ", 7: "THM",
    19: "PLD", 20: "MNK", 21: "WAR", 22: "DRG", 23: "BRD", 24: "WHM", 25: "BLM",
    26: "ACN", 27: "SMN", 28: "SCH", 29: "ROG", 30: "NIN", 31: "MCH", 32: "DRK",
    33: "AST", 34: "SAM", 35: "RDM", 36: "BLU", 37: "GNB", 38: "DNC", 39: "RPR",
    40: "SGE", 41: "VPR", 42: "PCT", 43: "BST",
}


@functools.lru_cache(maxsize=1)
def _load():
    try:
        with open(_DATA, encoding="utf-8") as fh:
            d = json.load(fh)
        return d.get("actions", {}), d.get("jobs", {})
    except Exception:
        return {}, {}


def has_data() -> bool:
    return bool(_load()[0])


def action_name(action_id: int) -> str:
    actions, _ = _load()
    return actions.get(str(action_id)) or f"#{action_id}"


def job_abbr(classjob_id: int):
    if not classjob_id:
        return None
    _, jobs = _load()
    return jobs.get(str(classjob_id)) or _JOBS.get(classjob_id)
