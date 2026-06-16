#!/usr/bin/env python3
"""
Mitigus XIV — Fase 1: proxy transparente (passthrough).

Coloca o PC no caminho do PS5 terminando o TCP: o WinDivert desvia o tráfego de
zona do PS5 para um relay local, que abre a conexão real upstream e bombeia os
bytes nos dois sentidos. Na Fase 1 NÃO há mitigação (passthrough) — o objetivo é
provar que o PS5 joga normalmente ATRAVÉS do proxy e que o caminho de volta passa
pelo PC. A mitigação entra nos hooks on_c2s/on_s2c na Fase 4.

Modos:
  --demo            valida o data-path localmente (relay + transform), SEM Admin
                    e SEM WinDivert. Sobe um echo upstream e mostra o eco em
                    MAIÚSCULAS para provar o hook de transform.

  --ps5-ip <IP>     modo real: requer Administrador. Roteamento já habilitado
                    (setup\\enable-routing.ps1) e gateway do PS5 = este PC.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mitigus.net.adapters import is_admin, primary_ipv4
from mitigus.paths import app_dir
from mitigus.proxy.conntrack import ConnTrack
from mitigus.proxy.relay import TransparentRelay


def _no_exe_guidance(hub, err=None):
    vendor = os.path.join(app_dir(), "vendor")
    print("! Não encontrei o ffxiv_dx11.exe (necessário para a mitigação no Dawntrail).")
    print("  Instale o TRIAL GRATUITO do FFXIV num PC Windows e copie o arquivo de:")
    print("     ...\\FINAL FANTASY XIV - A Realm Reborn\\game\\ffxiv_dx11.exe")
    print(f"  para:  {vendor}")
    if err:
        print(f"  (detalhe: {err})")
    try:
        os.makedirs(vendor, exist_ok=True)
        os.startfile(vendor)  # abre o Explorer na pasta (Windows)
    except Exception:
        pass
    if hub is not None:
        hub.set_info(mitigate=False, oodle_loaded=False, oodle_missing=True, vendor_path=vendor)
    print("  Abrindo o painel mesmo assim (sem mitigação até o arquivo estar lá).")


class _Tee:
    """Espelha o que vai pra tela também num arquivo (para o usuário enviar)."""

    def __init__(self, stream, fh):
        self._stream = stream
        self._fh = fh

    def write(self, s):
        if self._stream is not None:
            self._stream.write(s)
        try:
            self._fh.write(s)
            self._fh.flush()
        except Exception:
            pass

    def flush(self):
        try:
            if self._stream is not None:
                self._stream.flush()
            self._fh.flush()
        except Exception:
            pass


def _setup_logfile():
    """Salva todo o output (tela) num mitigus.log ao lado do app. Devolve o caminho."""
    if isinstance(sys.stdout, _Tee):
        return getattr(sys, "_mitigus_log_path", None)
    try:
        path = os.path.join(app_dir(), "mitigus.log")
        fh = open(path, "w", encoding="utf-8", buffering=1)
        fh.write(f"=== Mitigus XIV — log da sessão — {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        sys.stdout = _Tee(sys.stdout, fh)
        sys.stderr = _Tee(sys.stderr, fh)
        sys._mitigus_log_path = path
        return path
    except Exception:
        return None


def open_app_window(url, candidates=None) -> bool:
    """Abre o painel numa JANELA estilo app (Edge/Chrome em modo --app, sem abas/
    barra de endereço). Usa o Edge que já vem no Windows. Devolve True se abriu."""
    import subprocess

    def _from_app_paths(exe_name):
        # Caminho do navegador pelo registro (App Paths), pra achar mesmo fora do padrão.
        try:
            import winreg

            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(
                        root,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + exe_name,
                    ) as k:
                        return winreg.QueryValueEx(k, None)[0]
                except OSError:
                    continue
        except Exception:
            pass
        return None

    if candidates is None:
        candidates = [
            _from_app_paths("msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            _from_app_paths("chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        ]
    for exe in candidates:
        if exe and os.path.isfile(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=600,960"])
                return True
            except Exception:
                pass
    return False


def _open_panel(url, mode) -> None:
    if mode == "none":
        return
    if mode == "window" and open_app_window(url):
        print("  (abri o painel numa janela do app)")
        return
    try:
        import webbrowser

        webbrowser.open(url)
        print("  (abri o painel no seu navegador)")
    except Exception:
        pass


async def _demo() -> None:
    async def echo(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while True:
                d = await r.read(4096)
                if not d:
                    break
                w.write(d)
                await w.drain()
        finally:
            w.close()

    up = await asyncio.start_server(echo, "127.0.0.1", 0)
    up_addr = up.sockets[0].getsockname()
    relay = TransparentRelay(
        resolve=lambda peer: (up_addr[0], up_addr[1]),
        listen_host="127.0.0.1",
        listen_port=0,
        on_s2c=lambda b: b.upper(),
    )
    port = await relay.start()
    print("=== Mitigus XIV — Fase 1 (demo, sem Admin) ===")
    print(f"  relay em      : 127.0.0.1:{port}")
    print(f"  echo upstream : 127.0.0.1:{up_addr[1]}")
    print("  teste rápido em outro terminal:")
    print(f'    python -c "import socket;s=socket.create_connection((\'127.0.0.1\',{port}));'
          's.sendall(b\'oi mitigus\');print(s.recv(100))"')
    print("  esperado: b'OI MITIGUS'  (o transform on_s2c põe em maiúsculas)")
    print("  Ctrl+C encerra.")
    async with up:
        await relay.serve_forever()


def _opcode_date(defs):
    import re

    for d in defs:
        m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", d.Name or "")
        if m:
            return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return None


def _build_mitigation_factory(exe, opcodes_json, extra_delay, log, hub=None, capture=None):
    from mitigus.mitigation.mitigator import Mitigator
    from mitigus.protocol.opcodes import load_definitions, match_for_server

    print("  carregando definições de opcode...")
    state = {"defs": load_definitions(json_path=opcodes_json)}
    module = None
    if exe:
        from mitigus.oodle.oodle import OodleModule

        print(f"  carregando Oodle de {exe} ...")
        module = OodleModule.from_exe(exe)

    def _publish():
        if hub is not None:
            hub.set_info(opcodes_count=len(state["defs"]), opcodes_date=_opcode_date(state["defs"]))

    if hub is not None:
        hub.set_info(oodle_loaded=module is not None)
    _publish()

    def refresh():
        try:
            state["defs"] = load_definitions(json_path=opcodes_json, force_update=True)
        except Exception as e:
            log(f"falha ao atualizar opcodes: {e}")
            return {"ok": False, "error": str(e)}
        _publish()
        date = _opcode_date(state["defs"])
        log(f"opcodes atualizados ({len(state['defs'])} tabela(s), {date or '?'})")
        return {"ok": True, "count": len(state["defs"]), "date": date}

    def factory(peer, dest):
        opc = match_for_server(state["defs"], dest[0], dest[1])
        if hub is not None:
            hub.note_flow()
            from mitigus.net.datacenter import lookup as _dclookup
            dc = _dclookup(dest[0])
            hub.set_info(server_ip=dest[0], server_region=dc["region"], server_label=dc["label"])
        if opc is None:
            if hub is not None:
                hub.set_info(opcodes_matched=False, unmatched_server=dest[0])
            log(f"sem opcodes para o servidor {dest[0]}:{dest[1]} (região?) — passthrough")
            return None
        if hub is not None:
            hub.set_info(opcodes_matched=True, opcodes_active=opc.Name)
        oodle = None
        if module is not None:
            from mitigus.oodle.oodle import OodleHelper

            oodle = OodleHelper(module)
        return Mitigator(opc, oodle=oodle, extra_delay=extra_delay, on_log=log, hub=hub, capture=capture)

    return factory, refresh


def _run_full(ps5_ip, pc_ip, port, mitigate, exe, extra_delay, opcodes_json, panel, panel_host, panel_port, open_mode="browser", on_ready=None, prompt_reboot=True, capture_path=None, capture_sink=None) -> int:
    logpath = _setup_logfile()
    if logpath:
        print(f"  log desta sessão: {logpath}  (envie este arquivo para análise)")
    if not is_admin():
        print("! Modo real exige Administrador (WinDivert carrega driver de kernel).")
        return 2
    pc_ip = pc_ip or primary_ipv4()
    if not pc_ip:
        print("! Não consegui descobrir o IP do PC; passe --pc-ip.")
        return 2

    # Liga o PC como roteador (compartilha internet com o PS5). O IPEnableRouter só
    # vale APÓS reiniciar — se for o caso, oferece reiniciar agora (popup nativo).
    from mitigus.net.adapters import (enable_routing, reboot_pending, reboot_should_prompt,
                                       mark_reboot_dismissed, ask_yes_no, reboot_windows)
    enable_routing()
    from mitigus import i18n
    i18n.load_lang()  # idioma salvo (ou o do Windows) p/ o diálogo e os logs do hub
    reboot_needed = reboot_pending()  # alimenta o banner do painel
    if prompt_reboot and reboot_should_prompt():
        mark_reboot_dismissed()  # no máximo 1 popup por boot
        if ask_yes_no(i18n.t("dlg.reboot_title"), i18n.t("dlg.reboot_text")):
            reboot_windows(20)
            print("  Reiniciando o Windows em 20 segundos...")
            return 0
        print("  ! Sem reiniciar, o PS5/PS4 ficará SEM internet. Reinicie quando puder")
        print("    (ou clique em 'Reiniciar agora' no painel).")

    from mitigus.proxy.divert_nat import DivertNat, ProxyConfig
    from mitigus.proxy.masquerade import Masquerade

    hub = None
    if panel:
        from mitigus.net.adapters import routing_enabled
        from mitigus.panel.hub import ControlHub

        hub = ControlHub(extra_delay=extra_delay)
        hub.set_info(
            mode="proxy", pc_ip=pc_ip, ps5_ip=ps5_ip, admin=is_admin(),
            routing=routing_enabled(), mitigate=bool(mitigate),
            oodle_loaded=False, opcodes_count=0, log_path=logpath,
            reboot_pending=reboot_needed,
        )

    def log(m):
        print(f"  [mit] {m}")
        if hub is not None:
            hub.add_log(m)

    # Captura opcional (variante DPS). Dois modos, ambos default-off:
    #  - capture_sink: callable(direction, header, messages) ao vivo (ex.: meter)
    #  - capture_path: grava os segmentos IPC pós-Oodle num JSONL (run_capture)
    # capture_sink tem precedência. Só fazem sentido com mitigação (factory/Oodle).
    recorder = None
    if capture_path and mitigate and capture_sink is None:
        from mitigus.capture.recorder import SegmentRecorder

        recorder = SegmentRecorder(capture_path, started_ms=int(time.time() * 1000))
        print(f"  CAPTURA ligada -> {capture_path}")
        if hub is not None:
            hub.add_log(f"captura: gravando segmentos em {os.path.basename(capture_path)}")
    cap = capture_sink if capture_sink is not None else recorder

    factory = None
    refresh_opcodes = None
    if mitigate:
        from mitigus.oodle.locate import find_ffxiv_dx11

        exe = exe or find_ffxiv_dx11(base_dir=app_dir())
        if not exe:
            _no_exe_guidance(hub)  # cai pra passthrough; painel avisa "falta o decodificador"
        else:
            print(f"  ffxiv_dx11.exe: {exe}")
            try:
                factory, refresh_opcodes = _build_mitigation_factory(
                    exe, opcodes_json, extra_delay, log, hub=hub, capture=cap
                )
            except Exception as e:
                print(f"! Falha ao preparar a mitigação: {e}")
                _no_exe_guidance(hub, err=str(e))

    # Auto-atualiza os opcodes em segundo plano (best-effort): depois de um patch do
    # jogo, basta reabrir o Mitigus que ele pega as definições novas sozinho (mesma
    # fonte do XivAlexander). Se falhar/sem internet, mantém o cache. Não bloqueia.
    if refresh_opcodes:
        import threading

        threading.Thread(target=refresh_opcodes, daemon=True, name="mitigus-opcodes").start()

    panel_server = None
    if panel:
        from mitigus.panel.server import PanelServer

        panel_server = PanelServer(hub, host=panel_host, port=panel_port, on_update_opcodes=refresh_opcodes)

    ct = ConnTrack()
    cfg = ProxyConfig(ps5_ip=ps5_ip, pc_ip=pc_ip, proxy_port=port)

    async def go() -> None:
        async def _connect_upstream(host, port, timeout):
            # rota do upstream do jogo (PC->servidor):
            #  - socks5: manda por um VPS próprio; se o VPS falhar, cai pra DIRETA
            #            (um VPS ruim nunca derruba o jogo).
            #  - gpn/off: socket NORMAL. No modo GPN é de propósito — o tráfego sai
            #            pela rota do sistema, onde o ExitLag/NoPing/Mudfish do PC o
            #            captura pelos IPs do servidor e otimiza. O único cuidado é
            #            NÃO sequestrar pro SOCKS5 (senão rotearia duas vezes).
            route = hub.route() if hub is not None else None
            if route and route.get("mode") == "socks5" and route.get("host"):
                from mitigus.net.socks5 import open_via_socks5
                try:
                    return await open_via_socks5(
                        route["host"], int(route["port"]), host, port, timeout)
                except Exception as e:
                    log(f"[rota] SOCKS5 falhou ({e}); usando conexão direta")
            return await asyncio.wait_for(asyncio.open_connection(host, port), timeout)

        relay = TransparentRelay(
            resolve=lambda peer: ct.lookup(peer[0], peer[1]),
            listen_host="0.0.0.0",
            listen_port=cfg.proxy_port,
            processor_factory=factory,
            connect_upstream=_connect_upstream,
        )
        bound = await relay.start()
        cfg.proxy_port = bound
        # NAT geral (internet pro PS5/aparelho) — tudo que NÃO é o jogo. Prioridade
        # menor que o DivertNat, que desvia o FFXIV pro proxy primeiro.
        from mitigus.proxy.qos import BufferbloatController
        qos = BufferbloatController()
        masq = Masquerade(pc_ip, on_log=lambda s: log(f"[net] {s}"), priority=0, qos=qos)
        masq.start()
        # NAT do jogo (FFXIV -> proxy -> mitigação). Prioridade alta na camada forward.
        nat = DivertNat(cfg, ct, priority=1000)
        nat.start()

        # Poller do ping WAN (perna PC->servidor) via SIO_TCP_INFO — grátis, sem
        # tráfego extra. Alimenta o painel (ping/jitter/retransmissão).
        ping_task = None
        if hub is not None:
            async def _ping_poller():
                last = {"retrans": None}
                while True:
                    await asyncio.sleep(1.0)
                    hub.set_info(game_active=relay.active_count())
                    qos.set_enabled(hub.get_config().get("qos", False))
                    info = relay.sample_upstream_tcp_info()
                    if not info:
                        continue
                    qos.update_rtt(info["rtt_ms"])  # fecha o laço anti-bufferbloat
                    br = info.get("bytes_retrans")
                    delta = None
                    if br is not None:
                        if last["retrans"] is not None:
                            delta = max(0, br - last["retrans"])
                        last["retrans"] = br
                    hub.record_net(info["rtt_ms"], info["min_rtt_ms"], delta)
            ping_task = asyncio.create_task(_ping_poller())

        if panel_server is not None:
            pport = panel_server.start()
            from mitigus.net.adapters import open_firewall_port
            if open_firewall_port(pport):
                print(f"  firewall: porta {pport} liberada na rede local (painel no celular)")
            url_local = f"http://127.0.0.1:{pport}"
            print(f"  painel: http://{pc_ip}:{pport}  (no celular, na mesma rede)")
            _open_panel(url_local, open_mode)
            if on_ready:
                try:
                    on_ready(url_local, hub, refresh_opcodes)
                except Exception:
                    pass
        mode = "MITIGAÇÃO ATIVA" if factory else "passthrough"
        fase = "5" if (factory and panel_server) else ("4" if factory else "1")
        print(f"=== Mitigus XIV — Fase {fase} (proxy real, {mode}) ===")
        print(f"  PS5={cfg.ps5_ip or 'auto'}  PC={cfg.pc_ip}  proxy_port={bound}")
        print("  Ctrl+C encerra.")
        try:
            await relay.serve_forever()
        finally:
            if ping_task is not None:
                ping_task.cancel()
            nat.stop()
            masq.stop()
            if panel_server is not None:
                panel_server.stop()

    try:
        asyncio.run(go())
    except KeyboardInterrupt:
        pass
    finally:
        if recorder is not None:
            recorder.close()
            print(f"  captura encerrada: {recorder.bundles} bundles, "
                  f"{recorder.count} segmentos -> {capture_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Mitigus XIV — Fase 1 proxy transparente")
    p.add_argument("--demo", action="store_true", help="data-path local sem Admin/WinDivert")
    p.add_argument("--ps5-ip", help="(opcional) filtra só este IP; padrão: capta o PS5 automaticamente")
    p.add_argument("--pc-ip", help="IP do PC na rede do PS5 (auto se omitido)")
    p.add_argument("--port", type=int, default=0, help="porta do proxy (0 = efêmera)")
    p.add_argument("--mitigate", action="store_true", help="liga a mitigação (Fase 4)")
    p.add_argument("--exe", help="ffxiv_dx11.exe (necessário p/ --mitigate no Dawntrail)")
    p.add_argument("--extra-delay", type=float, default=0.075, help="margem de segurança (s)")
    p.add_argument("--opcodes-json", help="arquivo único de opcodes (senão baixa/usa cache)")
    p.add_argument("--panel", action="store_true", help="painel web liga/desliga + telemetria (Fase 5)")
    p.add_argument("--panel-host", default="0.0.0.0", help="host do painel (padrão: LAN)")
    p.add_argument("--panel-port", type=int, default=8080, help="porta do painel (padrão 8080)")
    p.add_argument("--no-open", action="store_true", help="não abrir o painel automaticamente")
    p.add_argument("--window", action="store_true", help="abrir o painel numa janela do app (Edge --app)")
    args = p.parse_args()

    if args.demo:
        try:
            asyncio.run(_demo())
        except KeyboardInterrupt:
            pass
        return 0

    if not (args.mitigate or args.panel or args.ps5_ip):
        p.error("nada a fazer: use --panel e/ou --mitigate (ou --demo). Veja --help.")
    open_mode = "none" if args.no_open else ("window" if args.window else "browser")
    return _run_full(
        args.ps5_ip, args.pc_ip, args.port, args.mitigate, args.exe, args.extra_delay,
        args.opcodes_json, args.panel, args.panel_host, args.panel_port, open_mode,
    )


if __name__ == "__main__":
    raise SystemExit(main())
