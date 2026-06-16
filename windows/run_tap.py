#!/usr/bin/env python3
"""
Mitigus XIV — TAP (validação read-only no SEU PC).

Prova a parte mais difícil e nunca testada (decodificador Oodle + casamento de
opcodes + detecção do weave) usando o SEU jogo de verdade, SEM modificar nada na
rede: é 100% passivo (WinDivert em modo SNIFF — só observa, nunca altera/reinjeta).

Como funciona:
  - Captura o tráfego do FFXIV do próprio PC (camada NETWORK, portas do jogo).
  - Reagrupa o stream TCP por conexão/direção (Oodle é stateful: precisa do começo).
  - Joga os bytes no Mitigator REAL (mesmo código de produção) em modo dry_run:
    ele DECODIFICA (Oodle), acha o ActionEffect e LOGA quanto de weave CORTARIA —
    mas NÃO reserializa nada (read-only).

O que você vê no terminal, ao usar habilidades em combate:
    [tap] C2S_ActionRequest actionId=.... sequence=....
    [tap] S2C_ActionEffect actionId=.... seq=.... wait=600ms->550ms rtt=90ms ...
  A seta "->" é o corte que ele FARIA. Se aparecer, está tudo funcionando.

IMPORTANTE (Oodle é stateful):
  Comece o tap ANTES de trocar de zona/logar. Depois que ele estiver rodando,
  TROQUE DE ZONA (teleporte/entre numa instância) pra abrir uma conexão NOVA — o
  tap precisa pegar a conexão DESDE O INÍCIO pra decodificar. Se você começar o
  tap no meio de uma conexão já aberta, ele não consegue decodificar aquela
  (refaça o zoneamento).

Uso (como Administrador):
    python run_tap.py            (precisa do ffxiv_dx11.exe em vendor\\ ou instalado)
    python run_tap.py --out luta.jsonl   (além de validar, GRAVA os segmentos IPC
                                          pós-Oodle p/ desofuscação offline — deob)
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mitigus.net.adapters import is_admin
from mitigus.net.ports import build_filter, format_ranges, port_in_ranges
from mitigus.paths import app_dir


class _Reasm:
    """Reassembler TCP mínimo por direção (ordena, deduplica retransmissões).

    Oodle é stateful: um buraco/duplicata desincroniza o decode do resto da
    conexão. Aqui tratamos o caso comum (LAN saudável, em ordem) e bufferizamos
    pacotes fora de ordem. Sem o ISN (não vimos o SYN) não dá pra decodificar.
    """

    def __init__(self) -> None:
        self.next = None          # próximo seq esperado (None = não vimos o início)
        self.buf: dict = {}       # seq -> payload (fora de ordem)

    def set_isn(self, syn_seq: int) -> None:
        self.next = (syn_seq + 1) & 0xFFFFFFFF  # os dados começam em seq+1 (após o SYN)

    def push(self, seq: int, payload: bytes) -> bytes:
        if self.next is None or not payload:
            return b""
        out = bytearray()
        diff = (seq - self.next) & 0xFFFFFFFF
        if diff == 0:                       # em ordem
            out += payload
            self.next = (self.next + len(payload)) & 0xFFFFFFFF
            while self.next in self.buf:    # drena o que estava bufferizado
                p = self.buf.pop(self.next)
                out += p
                self.next = (self.next + len(p)) & 0xFFFFFFFF
        elif diff < 0x80000000:             # futuro (buraco): bufferiza
            if len(self.buf) < 512:
                self.buf[seq] = payload
        else:                               # passado: retransmissão/sobreposição
            back = (self.next - seq) & 0xFFFFFFFF
            if back < len(payload):         # tem bytes novos no final
                newp = payload[back:]
                out += newp
                self.next = (self.next + len(newp)) & 0xFFFFFFFF
        return bytes(out)


class _Conn:
    def __init__(self, factory, client, server, log) -> None:
        self.client = client
        self.server = server
        self.c2s = _Reasm()
        self.s2c = _Reasm()
        self._factory = factory
        self._log = log
        self._started = False
        self.mit = None

    def begin(self) -> None:
        if self._started:
            return
        self._started = True
        self.mit = self._factory(self.client, self.server)
        if self.mit is None:
            self._log(f"conexão {self.server[0]}:{self.server[1]} sem opcodes (passthrough) "
                      f"— sua região está coberta? veja o aviso acima")
        else:
            self.mit.dry_run = True  # read-only: decodifica e detecta, mas não reserializa
            self._log(f"conexão de JOGO iniciada -> {self.server[0]}:{self.server[1]} "
                      f"(decodificando ao vivo; use habilidades em combate)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Mitigus XIV — TAP read-only (captura opcional)")
    ap.add_argument("--out", help="grava os segmentos IPC pós-Oodle num .jsonl (p/ deob)")
    args = ap.parse_args()

    print("=== Mitigus XIV — TAP (validação read-only do seu PC) ===")
    if not is_admin():
        print("! Rode como Administrador (o WinDivert carrega um driver de kernel).")
        return 2

    import pydivert
    from pydivert import Flag, Layer

    from mitigus.oodle.locate import find_ffxiv_dx11

    exe = find_ffxiv_dx11(base_dir=app_dir())
    if not exe:
        vendor = os.path.join(app_dir(), "vendor")
        print("! Falta o ffxiv_dx11.exe (necessário pro decodificador Oodle).")
        print(f"  Copie o arquivo do jogo para: {vendor}")
        print("  (fica em ...\\FINAL FANTASY XIV - A Realm Reborn\\game\\ffxiv_dx11.exe)")
        try:
            os.makedirs(vendor, exist_ok=True)
            os.startfile(vendor)
        except Exception:
            pass
        return 2
    print(f"  ffxiv_dx11.exe: {exe}")

    import run_proxy

    counters = {"req": 0, "eff": 0, "cut": 0}

    def log(m: str) -> None:
        if "C2S_ActionRequest" in m:
            counters["req"] += 1
        elif "S2C_ActionEffect" in m:
            counters["eff"] += 1
            if "->" in m:
                counters["cut"] += 1
        print(f"  [tap] {m}")

    recorder = None
    if args.out:
        from mitigus.capture.recorder import SegmentRecorder

        recorder = SegmentRecorder(args.out, started_ms=int(time.time() * 1000))
        print(f"  CAPTURA ligada -> {args.out}  (gravando segmentos pós-Oodle)")

    factory, _ = run_proxy._build_mitigation_factory(exe, None, 0.075, log, hub=None, capture=recorder)

    flt = build_filter()  # tcp and (porta do FFXIV em src OU dst)
    handle = pydivert.WinDivert(flt, layer=Layer.NETWORK, flags=Flag.SNIFF)
    handle.open()

    print(f"\n  Portas do jogo observadas: {format_ranges()}")
    print("  Capturando (passivo, NÃO altera nada). Ctrl+C encerra.")
    print("  >>> AGORA: dentro do jogo, TROQUE DE ZONA (teleporte) e entre em")
    print("      COMBATE usando habilidades. As linhas com '->' são os cortes. <<<\n")

    conns: dict = {}
    last_status = time.monotonic()
    try:
        for pkt in handle:
            tcp = pkt.tcp
            if tcp is None:
                continue

            if port_in_ranges(pkt.dst_port):       # cliente -> servidor (C2S)
                client = (pkt.src_addr, pkt.src_port)
                server = (pkt.dst_addr, pkt.dst_port)
                direction = "c2s"
            elif port_in_ranges(pkt.src_port):     # servidor -> cliente (S2C)
                client = (pkt.dst_addr, pkt.dst_port)
                server = (pkt.src_addr, pkt.src_port)
                direction = "s2c"
            else:
                continue

            conn = conns.get(client)
            if tcp.syn and not tcp.ack:            # SYN do cliente: nova conexão
                conn = _Conn(factory, client, server, log)
                conns[client] = conn
                conn.c2s.set_isn(tcp.seq_num)
                conn.begin()
            elif tcp.syn and tcp.ack and conn is not None:  # SYN-ACK do servidor
                conn.s2c.set_isn(tcp.seq_num)

            if conn is None or conn.mit is None:
                continue
            payload = bytes(pkt.payload or b"")
            if not payload:
                continue
            try:
                if direction == "c2s":
                    data = conn.c2s.push(tcp.seq_num, payload)
                    if data:
                        conn.mit.c2s(data)
                else:
                    data = conn.s2c.push(tcp.seq_num, payload)
                    if data:
                        conn.mit.s2c(data)
            except Exception as exc:
                log(f"(decode falhou nesta conexão: {exc!r} — troque de zona p/ refazer)")

            now = time.monotonic()
            if now - last_status >= 10.0:
                last_status = now
                print(f"  [status] conexões={len(conns)}  pedidos={counters['req']}  "
                      f"efeitos={counters['eff']}  CORTES={counters['cut']}")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            handle.close()
        except Exception:
            pass
        if recorder is not None:
            recorder.close()
            print(f"\n  captura: {recorder.bundles} bundles, {recorder.count} segmentos "
                  f"-> {args.out}")

    print("\n  ----------------------------------------------------------")
    print(f"  RESUMO: conexões={len(conns)}  ActionRequest={counters['req']}  "
          f"ActionEffect={counters['eff']}  CORTES detectados={counters['cut']}")
    if counters["cut"] > 0:
        print("  >>> FUNCIONOU. O Oodle decodificou, os opcodes casaram e o Mitigus")
        print("      detectou e calculou os cortes de weave no seu jogo real. <<<")
    elif counters["eff"] > 0:
        print("  Decodificou e viu efeitos, mas nenhum corte (talvez ping baixo —")
        print("  sem RTT alto não há o que cortar). Teste com mais latência/combate.")
    else:
        print("  Não decodifiquei nenhum efeito. Causas comuns: começou o tap no meio")
        print("  de uma conexão (troque de zona com o tap JÁ rodando), região sem")
        print("  opcodes, ou o exe do Oodle incompatível com o patch atual.")
    print("  ----------------------------------------------------------")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
