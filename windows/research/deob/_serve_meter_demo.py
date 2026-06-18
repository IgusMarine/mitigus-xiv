"""DEV: sobe o MeterServer com dados de exemplo p/ verificar a UI (Neon Bars).
Não é produção — só para o preview. Dados mock (party com jobs/cores)."""
import os
import sys
import time

WIN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WIN)

from mitigus.meter.server import MeterServer
from mitigus.meter.tracker import DpsTracker

t = DpsTracker()
party = [
    (0xA, "Você", "SAM", True, 32.0),
    (0xB, "Y'shtola", "BLM", False, 27.5),
    (0xC, "Estinien", "DRG", False, 21.0),
    (0xD, "Alphinaud", "SCH", False, 11.5),
    (0xE, "Alisaie", "RDM", False, 8.0),
]
TOTAL, DUR_MS, HITS = 2_850_000, 120_000, 48
ACTIONS = [36937, 16145, 16137, 16165, 7]  # nomes reais só p/ ver a linha "top"
for idx, (aid, name, job, is_self, pct) in enumerate(party):
    t.set_actor_info(aid, name=name, job=job, level=100)
    per = int(TOTAL * pct / 100 / HITS)
    act = ACTIONS[idx % len(ACTIONS)]
    for i in range(HITS):
        t.record_damage(aid, per, is_crit=(i % 4 == 0), is_direct=(i % 7 == 0),
                        ts_ms=int(DUR_MS * i / HITS), action_id=act)
t.mark_self(0xA)

srv = MeterServer(t, host="127.0.0.1", port=8099)
srv.start()
print("meter-demo em http://127.0.0.1:8099", flush=True)
while True:
    time.sleep(3600)
