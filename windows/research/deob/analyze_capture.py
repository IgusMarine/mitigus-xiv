"""
Analisador offline de DPS: captura (.jsonl) -> desofusca -> parseia combate ->
tabela de DPS. Valida a MATEMÁTICA do dano contra dados reais antes do meter
ao vivo.

Mostra primeiro um HISTOGRAMA de tipos de efeito (pra cravar o que conta como
dano no patch real), depois DPS por ator/ação.

Uso:
    python analyze_capture.py <captura.jsonl> [--version 2026.06.10.0000.0000]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # windows/ -> import mitigus.*

from mitigus.deob import Deobfuscator               # noqa: E402
from mitigus.deob.constants import LATEST            # noqa: E402
from mitigus.meter.combat import parse_action_effect, DAMAGE_TYPES  # noqa: E402


def _variant_map(constants):
    out = {}
    for name, n in (("ActionEffect01", 1), ("ActionEffect08", 8), ("ActionEffect16", 16),
                    ("ActionEffect24", 24), ("ActionEffect32", 32)):
        op = constants.obfuscated_opcodes.get(name)
        if op is not None:
            out[op] = n
    return out


def analyze(path, version=LATEST):
    deob = Deobfuscator(version)
    variants = _variant_map(deob.constants)
    init_op = deob.constants.unknown_obfuscation_init_opcode

    type_hist = defaultdict(lambda: [0, 0])          # type -> [count, soma_value]
    by_actor = defaultdict(lambda: {"dmg": 0, "hits": 0, "crit": 0, "dh": 0})
    by_action = defaultdict(lambda: {"dmg": 0, "hits": 0})
    ts_min = ts_max = None
    n_ae = 0

    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if "op" not in r:
            continue
        op, md = r["op"], bytes.fromhex(r["data"])
        if op == init_op:
            deob.feed_initializer(md)
            continue
        if op not in variants or not deob.is_active:
            continue

        clean = deob.unscramble_copy(md)
        ae = parse_action_effect(clean, variants[op])
        if ae is None:
            continue
        n_ae += 1
        src = r.get("src", 0)
        ts = r.get("ts", 0)
        if ts:
            ts_min = ts if ts_min is None else min(ts_min, ts)
            ts_max = ts if ts_max is None else max(ts_max, ts)

        for e in ae.effects:
            type_hist[e.type][0] += 1
            type_hist[e.type][1] += e.value
            if e.is_damage:
                by_actor[src]["dmg"] += e.value
                by_actor[src]["hits"] += 1
                by_actor[src]["crit"] += int(e.is_crit)
                by_actor[src]["dh"] += int(e.is_direct)
                by_action[ae.action_id]["dmg"] += e.value
                by_action[ae.action_id]["hits"] += 1

    dur = (ts_max - ts_min) / 1000.0 if (ts_min and ts_max and ts_max > ts_min) else 0.0

    print(f"== análise {os.path.basename(path)} (versão {version}) ==")
    print(f"   {n_ae} ActionEffect | duração ~{dur:.1f}s\n")

    print("  HISTOGRAMA de tipos de efeito (type -> qtd, soma dos values):")
    for t, (cnt, tot) in sorted(type_hist.items(), key=lambda kv: -kv[1][1]):
        tag = " <- DANO" if t in DAMAGE_TYPES else ""
        print(f"    type 0x{t:02x}: {cnt:4d}x  soma={tot:>10d}{tag}")
    print()

    print("  DPS por ATOR (source_actor):")
    for actor, s in sorted(by_actor.items(), key=lambda kv: -kv[1]["dmg"]):
        dps = s["dmg"] / dur if dur else 0.0
        critp = 100 * s["crit"] / s["hits"] if s["hits"] else 0
        dhp = 100 * s["dh"] / s["hits"] if s["hits"] else 0
        print(f"    actor {actor:#010x}: {s['dmg']:>9d} dano | {s['hits']:3d} hits | "
              f"crit {critp:4.0f}% | DH {dhp:4.0f}% | {dps:8.1f} DPS")
    print()

    print("  TOP ações por dano:")
    top = sorted(by_action.items(), key=lambda kv: -kv[1]["dmg"])[:12]
    for aid, s in top:
        avg = s["dmg"] / s["hits"] if s["hits"] else 0
        print(f"    action {aid:#06x}: {s['dmg']:>9d} total | {s['hits']:3d} hits | média {avg:7.0f}")

    return type_hist, by_actor, dur


def main():
    p = argparse.ArgumentParser(description="Analisador offline de DPS (captura -> deob -> combate)")
    p.add_argument("capture")
    p.add_argument("--version", default=LATEST)
    args = p.parse_args()
    analyze(args.capture, args.version)


if __name__ == "__main__":
    main()
