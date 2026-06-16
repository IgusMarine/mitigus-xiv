import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mitigus.deob import Deobfuscator
from mitigus.deob.constants import LATEST

CAP = r"D:/TRABALHOS/Mitigus XIV/windows/luta.jsonl"
deob = Deobfuscator(LATEST)
ps_op = deob.constants.obfuscated_opcodes["PlayerSpawn"]
init_op = deob.constants.unknown_obfuscation_init_opcode

JOBS = {19:"PLD",20:"MNK",21:"WAR",22:"DRG",23:"BRD",24:"WHM",25:"BLM",26:"ACN",
        27:"SMN",28:"SCH",29:"ROG",30:"NIN",31:"MCH",32:"DRK",33:"AST",34:"SAM",
        35:"RDM",36:"BLU",37:"GNB",38:"DNC",39:"RPR",40:"SGE",41:"VPR",42:"PCT"}

for line in open(CAP, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    r = json.loads(line)
    if "op" not in r:
        continue
    if r["op"] == init_op:
        deob.feed_initializer(bytes.fromhex(r["data"]))
        continue
    if r["op"] == ps_op and deob.is_active:
        c = deob.unscramble_copy(bytes.fromhex(r["data"]))
        name = bytes(c[610:642]).split(b"\x00")[0].decode("utf-8", "replace")
        print(f"PlayerSpawn nome={name!r} len={len(c)}")
        # candidatos a JOB (valor 19..42) em todo o buffer, com vizinhos
        print("  posicoes com valor de JOB combativo (19..42):")
        for o in range(len(c)):
            if 19 <= c[o] <= 42:
                nb = c[max(0,o-2):o+3].hex(" ")
                print(f"    buf {o:3d} (corpo {o-16:3d}) = {c[o]:2d} {JOBS[c[o]]:4s}  viz[{nb}]")
        # bytes em faixa de nivel (80..100) — classJob costuma estar colado no level
        print("  posicoes com valor de NIVEL (80..100):")
        for o in range(len(c)):
            if 80 <= c[o] <= 100:
                print(f"    buf {o:3d} (corpo {o-16:3d}) = {c[o]:3d} (0x{c[o]:02x}) viz[{c[max(0,o-2):o+3].hex(' ')}]")
        break
