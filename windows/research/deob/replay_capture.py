"""
Replay/validação offline de uma captura (.jsonl do run_capture) pelo deob.

Lê o dump de segmentos IPC, acha o pacote inicializador de ofuscação (deriva as
3 chaves DA REDE), desofusca os ActionEffect e imprime action_id + valores de
dano. É o passo que VALIDA o deob contra tráfego real do console:

  - Se os action_id saírem plausíveis (≠0, < 0x10000) e os valores de dano
    fizerem sentido (dezenas a milhares), a desofuscação está correta.
  - Se saírem como lixo (números enormes/aleatórios), a chave/algoritmo não
    bate com o patch -> conferir a versão (--version) e os dados .bin.

NÃO é o DPS meter final — é o validador. O parser de combate completo
(potência -> DPS por job) vem depois, uma vez validado.

Uso:
    python replay_capture.py <captura.jsonl> [--version 2026.06.10.0000.0000]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# windows/ no path -> import mitigus.deob (research/deob -> windows = 2 níveis acima)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mitigus.deob import Deobfuscator   # noqa: E402
from mitigus.deob.constants import LATEST  # noqa: E402

# offsets no buffer que começa no HEADER IPC (16B) -> corpo do ActionEffect:
OFF_ACTION_ID = 24       # u32  (corpo +8)  [OFUSCADO -> precisa do deob]
OFF_SOURCE_SEQ = 40      # u16  (corpo +24)
OFF_EFFECT_COUNT = 49    # u8   (corpo +33)
OFF_EFFECT_VALUES = 64   # u16 a cada 8 bytes [OFUSCADO -> precisa do deob]


def _u(buf, off, n):
    return int.from_bytes(buf[off:off + n], "little")


def _variant_map(constants):
    """opcode_value -> nº de targets (1/8/16/24/32)."""
    out = {}
    for name, n in (("ActionEffect01", 1), ("ActionEffect08", 8),
                    ("ActionEffect16", 16), ("ActionEffect24", 24),
                    ("ActionEffect32", 32)):
        op = constants.obfuscated_opcodes.get(name)
        if op is not None:
            out[op] = n
    return out


def replay(path, version=LATEST, max_show=40):
    deob = Deobfuscator(version)
    init_op = deob.constants.unknown_obfuscation_init_opcode
    variants = _variant_map(deob.constants)

    n_segs = n_init = n_effects = n_plausible = 0
    print(f"== replay {os.path.basename(path)} (versão {version}) ==")

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if "op" not in rec:
                continue
            n_segs += 1
            op = rec["op"]
            md = bytes.fromhex(rec["data"])

            if op == init_op:
                active = deob.feed_initializer(md)
                n_init += 1
                print(f"  [init] op=0x{op:04x} mode={'ON' if active else 'off'} "
                      f"keys={[hex(k) for k in deob.keygen.keys]}")
                continue

            if op in variants and deob.is_active:
                clean = deob.unscramble_copy(md)
                action_id = _u(clean, OFF_ACTION_ID, 4)
                seq = _u(clean, OFF_SOURCE_SEQ, 2)
                count = _u(clean, OFF_EFFECT_COUNT, 1)
                n = min(8 * variants[op], 64)
                vals = [_u(clean, OFF_EFFECT_VALUES + i * 8, 2) for i in range(n)]
                vals = [v for v in vals if v]
                plausible = 0 < action_id < 0x10000 and count <= 64
                n_effects += 1
                n_plausible += int(plausible)
                if n_effects <= max_show:
                    flag = "ok " if plausible else "?? "
                    print(f"  [{flag}] action_id={action_id:#06x} seq={seq:#06x} "
                          f"count={count} dano={vals[:8]}")

    print(f"-- {n_segs} segmentos | {n_init} init | {n_effects} ActionEffect | "
          f"{n_plausible} plausíveis "
          f"({100 * n_plausible // n_effects if n_effects else 0}%)")
    if n_init == 0:
        print("  ! Nenhum pacote inicializador encontrado — captura começou tarde "
              "demais (ofuscação só liga na troca de zona). Capture desde o login.")
    elif n_effects and n_plausible == n_effects:
        print("  [OK] desofuscacao consistente: todos os ActionEffect plausiveis.")
    elif n_effects and n_plausible == 0:
        print("  [X] tudo implausivel - versao errada? confira --version e os .bin.")
    return n_effects, n_plausible


def main():
    p = argparse.ArgumentParser(description="Replay/validação de captura pelo deob")
    p.add_argument("capture", help="arquivo .jsonl do run_capture")
    p.add_argument("--version", default=LATEST, help="versão do jogo (default: a mais nova)")
    args = p.parse_args()
    replay(args.capture, args.version)


if __name__ == "__main__":
    main()
