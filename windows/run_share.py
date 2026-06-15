#!/usr/bin/env python3
"""
Teste isolado do NAT (masquerade) — Fase de rede.

Liga SÓ o compartilhamento de internet (sem painel, sem mitigação): um aparelho
(celular/PS5) com o gateway apontando pro PC passa a ter internet PELO PC, sem
depender do roteador rotear o tráfego de passagem.

Use isto pra validar com o CELULAR antes de integrar no app:

    python run_share.py            (como Administrador)

Depois, no celular: IP estático, Gateway = IP do PC, DNS 1.1.1.1, e teste a net.
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mitigus.net.adapters import (
    enable_routing,
    is_admin,
    primary_ipv4,
    remoteaccess_running,
    routing_enabled,
)


def _diag() -> int:
    print("=== Mitigus XIV — teste DEFINITIVO de captura (NETWORK + FORWARD) ===")
    if not is_admin():
        print("! Rode como Administrador.")
        return 2
    pc_ip = primary_ipv4() or ""
    lan_prefix = ".".join(pc_ip.split(".")[:3]) + "."
    p = pc_ip.split(".")
    lan_lo = ".".join(p[:3] + ["0"])
    lan_hi = ".".join(p[:3] + ["255"])
    import pydivert
    from pydivert import Flag, Layer

    print(f"  IP do PC: {pc_ip}   (LAN {lan_prefix}0/24)")
    print(f"  IPEnableRouter: {routing_enabled()}  |  RemoteAccess: {remoteaccess_running()}")
    print("  Observando nas DUAS camadas, SEM modificar nada (passivo). Zero risco.\n")

    # Capturamos o tráfego do aparelho (origem na LAN, não o PC) em DUAS camadas ao
    # mesmo tempo, pra responder de vez ONDE ele aparece:
    #   NETWORK         = pacotes de/para o PRÓPRIO PC (autor do WinDivert: transit NÃO entra aqui)
    #   NETWORK_FORWARD = pacotes de PASSAGEM (transit), só se o Windows encaminhar
    # Em cada camada, separamos destino "internet" (fora da LAN) de "interno" (na LAN).
    src_clause = (f"ip.SrcAddr >= {lan_lo} and ip.SrcAddr <= {lan_hi} and ip.SrcAddr != {pc_ip}")
    net_filter = f"inbound and (tcp or udp) and {src_clause}"
    fwd_filter = f"(tcp or udp) and {src_clause}"

    # Abre os dois handles em SEQUÊNCIA (1º instala o driver, 2º anexa) p/ evitar a corrida.
    net_h = pydivert.WinDivert(net_filter, layer=Layer.NETWORK, flags=Flag.SNIFF)
    net_h.open()
    fwd_h = pydivert.WinDivert(fwd_filter, layer=Layer.NETWORK_FORWARD, flags=Flag.SNIFF)
    fwd_h.open()

    c = {"net_net": 0, "net_lan": 0, "fwd_net": 0, "fwd_lan": 0}
    flows = {}  # src_ip -> set de destinos internet

    def _sniff(handle, key_net, key_lan):
        try:
            for pkt in handle:
                if pkt.dst_addr.startswith(lan_prefix):
                    c[key_lan] += 1
                else:
                    c[key_net] += 1
                    flows.setdefault(pkt.src_addr, set()).add(pkt.dst_addr)
        except Exception:
            pass

    threads = [
        threading.Thread(target=_sniff, args=(net_h, "net_net", "net_lan"), daemon=True),
        threading.Thread(target=_sniff, args=(fwd_h, "fwd_net", "fwd_lan"), daemon=True),
    ]
    for t in threads:
        t.start()

    dur = 20
    print(f"  Capturando por {dur}s (para sozinho — NÃO precisa de Ctrl+C).")
    print("  >>> NO CELULAR/PS5 (com Gateway = IP do PC), ABRA UM SITE AGORA <<<\n")
    for left in range(dur, 0, -1):
        if left % 5 == 0 or left <= 3:
            print(f"    ...{left}s   NETWORK(internet)={c['net_net']}  "
                  f"FORWARD(internet)={c['fwd_net']}")
        time.sleep(1)

    for h in (net_h, fwd_h):
        try:
            h.close()  # destrava o sniff
        except Exception:
            pass
    for t in threads:
        t.join(timeout=2)

    internet = c["net_net"] + c["fwd_net"]
    lan = c["net_lan"] + c["fwd_lan"]

    print("\n  ----------------------------------------------------------")
    print(f"  CAMADA NETWORK : {c['net_net']:>4} pra internet | {c['net_lan']:>4} interno (LAN)")
    print(f"  CAMADA FORWARD : {c['fwd_net']:>4} pra internet | {c['fwd_lan']:>4} interno (LAN)")
    print("  ----------------------------------------------------------")
    if internet > 0:
        canal = "FORWARD" if c["fwd_net"] >= c["net_net"] else "NETWORK"
        print(f"  >>> FUNCIONA — o tráfego do aparelho aparece (canal: {canal}). <<<")
        print("  O Windows está encaminhando o aparelho pra internet. Falta só o NAT.")
        print("  Próximo passo: 'python run_share.py' (e teste a internet no aparelho).")
    elif lan > 0:
        print("  >>> PARCIAL: os quadros CHEGAM, mas nada vai pra internet por IPv4. <<<")
        print("  Vejo o aparelho falando com a LAN/PC, mas nenhum pacote IPv4 pra fora.")
        print("  Quase certo IPv6: o aparelho sai pela internet por IPv6 (nosso NAT é")
        print("  IPv4). SOLUÇÃO: desligue o IPv6 no aparelho e rode de novo.")
        print(f"    (Confirme também: Gateway do aparelho = {pc_ip}?)")
    else:
        print("  >>> NÃO chegou NADA em nenhuma camada. <<<")
        print("  Os quadros do aparelho não estão chegando ao WinDivert. Confirme:")
        print(f"    1) Gateway do aparelho = {pc_ip} (e IP fixo na mesma faixa)?")
        print("    2) Você abriu um site NO APARELHO durante a captura?")
        print("    3) PC e aparelho no MESMO switch/cabo (sem isolamento de Wi-Fi)?")
        print("  Se persistir, os quadros não chegam à placa e o caminho é interface")
        print("  virtual (Wintun/Hyper-V). Me mande este resultado.")
    if flows:
        print("\n  Aparelhos vistos indo pra internet:")
        for ip, dsts in sorted(flows.items()):
            print(f"    {ip} -> {len(dsts)} destino(s) (ex.: {', '.join(list(dsts)[:3])})")
    print("  ----------------------------------------------------------")
    return 0


def main() -> int:
    if "--diag" in sys.argv:
        return _diag()

    print("=== Mitigus XIV — teste de NAT (compartilhamento) ===")
    if not is_admin():
        print("! Rode como Administrador (o WinDivert carrega um driver de kernel).")
        return 2

    pc_ip = primary_ipv4()
    if not pc_ip:
        print("! Não achei o IP do PC.")
        return 2

    print(f"  IP do PC: {pc_ip}")
    print("  Ligando o roteamento...")
    enable_routing()
    rt = routing_enabled()
    ra = remoteaccess_running()
    print(f"  IPEnableRouter (registro): {rt}")
    print(f"  serviço RemoteAccess rodando: {ra}")
    if not (rt and ra):
        print()
        print("  ====================================================")
        print("   ATENÇÃO: o encaminhamento pode NÃO estar ativo.")
        print("   Se 'saída' ficar em 0, REINICIE O PC e rode de novo")
        print("   (o IPEnableRouter do Windows só vale após reiniciar).")
        print("  ====================================================")

    from mitigus.proxy.masquerade import Masquerade

    masq = Masquerade(pc_ip, on_log=lambda s: print(f"  [nat] {s}"))
    masq.start()

    print()
    print("  NAT ATIVO. No aparelho (celular/PS5), configure:")
    print(f"     Gateway padrão = {pc_ip}   |   DNS = 1.1.1.1")
    print("  e teste abrir um site. Ctrl+C encerra.")
    print()
    try:
        while True:
            time.sleep(2)
            print(f"  [stats] saída={masq.out_packets}  retorno(casados)={masq.in_matched}  "
                  f"fluxos={len(masq.nat)}")
    except KeyboardInterrupt:
        pass
    finally:
        masq.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
