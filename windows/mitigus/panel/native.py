"""
Painel NATIVO (tkinter) — janela do Windows, sem navegador.

Por que existe: o painel web depende do navegador do usuário (renderizar HTML +
rodar JS + fazer fetch). Em alguns Windows/navegadores isso falha e a tela não
atualiza. Esta janela lê o `ControlHub` DIRETO (mesmo processo, mesma memória),
num timer do próprio tkinter — então é impossível "não atualizar": os mesmos dados
que o Mitigator grava aparecem aqui na hora.

Roda na thread PRINCIPAL (tkinter exige); o proxy/mitigação roda numa thread de
fundo. O hub é thread-safe (tem lock), então a leitura/escrita cruzada é segura.
Sem dependência nova: tkinter é stdlib e empacota em qualquer Windows.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

import tkinter as tk

BG = "#0e1726"; CARD = "#172234"; LINE = "#283449"
TXT = "#eaf1fb"; MUTED = "#8ea2bd"; FAINT = "#5c6f8a"
ACCENT = "#5cc8ee"; ON = "#34d399"; WARN = "#f5c451"; BAD = "#fb7185"; OFF = "#3b4a61"
F = "Segoe UI"


class NativePanel:
    def __init__(self, hub, gateway_ip: Optional[str] = None, phone_url: Optional[str] = None,
                 on_update_opcodes: Optional[Callable] = None,
                 on_reboot: Optional[Callable] = None):
        self.hub = hub
        self.gateway_ip = gateway_ip or "—"
        self.phone_url = phone_url
        self._on_update_opcodes = on_update_opcodes
        self._on_reboot = on_reboot
        self._last_log = None
        self._margin_after = None
        self._building_margin = False

        self.root = tk.Tk()
        self.root.title("Mitigus XIV")
        self.root.configure(bg=BG)
        self.root.geometry("440x720")
        self.root.minsize(420, 640)
        try:
            import os
            from ..paths import resource_dir
            self.root.iconbitmap(os.path.join(resource_dir(), "mitigus.ico"))
        except Exception:
            pass

        self.v = {}  # StringVars
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()

    # ---- helpers de layout ----------------------------------------------
    def _card(self, parent, pady=(0, 10)):
        c = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        c.pack(fill="x", padx=14, pady=pady)
        return c

    def _var(self, key, val=""):
        self.v[key] = tk.StringVar(value=val)
        return self.v[key]

    def _build(self):
        # cabeçalho
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=14, pady=(14, 8))
        tk.Label(head, text="◆ Mitigus XIV", bg=BG, fg=ACCENT,
                 font=(F, 16, "bold")).pack(side="left")
        tk.Label(head, textvariable=self._var("conn", "iniciando…"), bg=BG, fg=MUTED,
                 font=(F, 10)).pack(side="right")

        # banner de reinício (escondido até precisar)
        self.reboot_frame = tk.Frame(self.root, bg="#3a2c10", highlightbackground=WARN,
                                     highlightthickness=1)
        tk.Label(self.reboot_frame, text="⟳  Falta reiniciar o Windows",
                 bg="#3a2c10", fg="#fff", font=(F, 11, "bold")).pack(side="left", padx=12, pady=10)
        tk.Button(self.reboot_frame, text="Reiniciar", bg=WARN, fg="#1a1408", relief="flat",
                  font=(F, 10, "bold"), cursor="hand2", command=self._reboot).pack(
                      side="right", padx=12, pady=8)

        # toggle da mitigação
        self.toggle_btn = tk.Button(self.root, textvariable=self._var("toggle", "MITIGAÇÃO"),
                                    bg=ON, fg="#06210f", relief="flat", font=(F, 14, "bold"),
                                    cursor="hand2", pady=14, command=self._toggle)
        self.toggle_btn.pack(fill="x", padx=14, pady=(2, 12))

        # hero do corte
        hero = self._card(self.root)
        tk.Label(hero, text="ÚLTIMO CORTE DE ANIMATION LOCK", bg=CARD, fg=FAINT,
                 font=(F, 8, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        tk.Label(hero, textvariable=self._var("cut", "—"), bg=CARD, fg=ACCENT,
                 font=(F, 30, "bold")).pack(anchor="w", padx=16)
        tk.Label(hero, textvariable=self._var("saved", ""), bg=CARD, fg=ON,
                 font=(F, 11, "bold")).pack(anchor="w", padx=16, pady=(0, 14))

        # stats (ping / ações / economizado)
        strip = tk.Frame(self.root, bg=BG)
        strip.pack(fill="x", padx=14, pady=(0, 10))
        for i, (key, label) in enumerate((("ping", "SEU PING"), ("acts", "AÇÕES"),
                                          ("saved_tot", "ECONOMIZADO"))):
            cell = tk.Frame(strip, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            cell.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0))
            strip.grid_columnconfigure(i, weight=1)
            tk.Label(cell, textvariable=self._var(key, "—"), bg=CARD, fg=TXT,
                     font=(F, 16, "bold")).pack(pady=(11, 0))
            tk.Label(cell, text=label, bg=CARD, fg=FAINT, font=(F, 8)).pack(pady=(0, 11))

        # rede
        net = self._card(self.root)
        tk.Label(net, textvariable=self._var("net_title", "REDE"), bg=CARD, fg=ACCENT,
                 font=(F, 9, "bold")).pack(anchor="w", padx=16, pady=(12, 6))
        netrow = tk.Frame(net, bg=CARD)
        netrow.pack(fill="x", padx=16, pady=(0, 12))
        self.jit_label = tk.Label(netrow, textvariable=self._var("jit", "—"), bg=CARD,
                                  fg=ON, font=(F, 14, "bold"))
        for txt, key, lab in (("wan", "wan", "rede (PC→serv)"),):
            pass
        tk.Label(netrow, textvariable=self._var("wan", "—"), bg=CARD, fg=TXT,
                 font=(F, 14, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(netrow, text="rede · PC→serv", bg=CARD, fg=FAINT, font=(F, 8)).grid(
            row=1, column=0, sticky="w")
        self.jit_label.grid(row=0, column=1, sticky="e", padx=(30, 0))
        tk.Label(netrow, text="estabilidade", bg=CARD, fg=FAINT, font=(F, 8)).grid(
            row=1, column=1, sticky="e", padx=(30, 0))
        netrow.grid_columnconfigure(0, weight=1)
        netrow.grid_columnconfigure(1, weight=1)
        tk.Label(net, textvariable=self._var("netnote", ""), bg=CARD, fg=MUTED,
                 font=(F, 9), wraplength=380, justify="left").pack(anchor="w", padx=16, pady=(0, 12))

        # margem (slider)
        mcard = self._card(self.root)
        mhead = tk.Frame(mcard, bg=CARD)
        mhead.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(mhead, text="Margem de segurança", bg=CARD, fg=TXT, font=(F, 10, "bold")).pack(side="left")
        tk.Label(mhead, textvariable=self._var("margin_val", "75 ms"), bg=CARD, fg=ACCENT,
                 font=(F, 11, "bold")).pack(side="right")
        self.margin = tk.Scale(mcard, from_=60, to=150, resolution=5, orient="horizontal",
                               bg=CARD, fg=TXT, troughcolor=BG, highlightthickness=0,
                               showvalue=0, command=self._on_margin)
        self.margin.set(75)
        self.margin.pack(fill="x", padx=14, pady=(2, 4))
        # qos
        self.qos_var = tk.IntVar(value=0)
        tk.Checkbutton(mcard, text="Anti-bufferbloat (segura downloads do PS5)",
                       variable=self.qos_var, command=self._on_qos, bg=CARD, fg=MUTED,
                       selectcolor=BG, activebackground=CARD, activeforeground=TXT,
                       font=(F, 9), anchor="w").pack(fill="x", padx=14, pady=(0, 12))

        # status
        st = self._card(self.root)
        tk.Label(st, text="STATUS DO SISTEMA", bg=CARD, fg=ACCENT, font=(F, 9, "bold")).pack(
            anchor="w", padx=16, pady=(12, 4))
        self.checks = {}
        for key, lab in (("admin", "Administrador"), ("routing", "PC como roteador"),
                         ("opcodes", "Opcodes do jogo"), ("oodle", "Decodificador"),
                         ("ps5", "PS5/PS4 conectado")):
            row = tk.Frame(st, bg=CARD)
            row.pack(fill="x", padx=16, pady=2)
            dot = tk.Label(row, text="•", bg=CARD, fg=FAINT, font=(F, 12, "bold"), width=2)
            dot.pack(side="left")
            tk.Label(row, text=lab, bg=CARD, fg=TXT, font=(F, 10)).pack(side="left")
            if key == "opcodes" and self._on_update_opcodes:
                self._opc_btn = tk.Button(row, text="Atualizar", bg=CARD, fg=ACCENT, relief="flat",
                                          font=(F, 8, "bold"), cursor="hand2", bd=0,
                                          activebackground=CARD, activeforeground=TXT,
                                          command=self._update_opcodes)
                self._opc_btn.pack(side="right", padx=(8, 0))
            stv = tk.Label(row, textvariable=self._var("st_" + key, "—"), bg=CARD, fg=MUTED,
                           font=(F, 9))
            stv.pack(side="right")
            self.checks[key] = dot
        tk.Label(st, textvariable=self._var("gateway", ""), bg=CARD, fg=MUTED, font=(F, 9),
                 wraplength=380, justify="left").pack(anchor="w", padx=16, pady=(8, 12))

        # log
        lcard = self._card(self.root, pady=(0, 14))
        tk.Label(lcard, text="REGISTRO", bg=CARD, fg=ACCENT, font=(F, 9, "bold")).pack(
            anchor="w", padx=16, pady=(12, 4))
        self.logbox = tk.Text(lcard, height=8, bg="#0a111e", fg="#93accb", relief="flat",
                              font=("Consolas", 8), wrap="word", state="disabled",
                              highlightthickness=1, highlightbackground=LINE)
        self.logbox.pack(fill="both", expand=True, padx=14, pady=(0, 12))

    # ---- ações ----------------------------------------------------------
    def _toggle(self):
        try:
            self.hub.toggle()
        except Exception:
            pass

    def _on_margin(self, val):
        if self._building_margin:
            return
        if self._margin_after:
            self.root.after_cancel(self._margin_after)
        self._margin_after = self.root.after(
            250, lambda: self._push_margin(int(float(val))))

    def _push_margin(self, ms):
        try:
            self.hub.set_config(extra_delay=ms / 1000.0)
        except Exception:
            pass

    def _on_qos(self):
        try:
            self.hub.set_config(qos=bool(self.qos_var.get()))
        except Exception:
            pass

    def _reboot(self):
        if self._on_reboot:
            self._on_reboot()

    def _update_opcodes(self):
        if not self._on_update_opcodes:
            return
        btn = self._opc_btn
        btn.configure(text="...", state="disabled")

        def work():
            ok = True
            try:
                r = self._on_update_opcodes()  # baixa da fonte do XivAlexander
                ok = not (isinstance(r, dict) and r.get("ok") is False)
            except Exception:
                ok = False

            def done():
                btn.configure(text="OK" if ok else "erro", state="normal")
                self.root.after(1600, lambda: btn.configure(text="Atualizar"))
            try:
                self.root.after(0, done)
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_close(self):
        import os
        self.root.destroy()
        os._exit(0)

    # ---- atualização (timer do tkinter) ---------------------------------
    def _set(self, key, val):
        self.v[key].set(val)

    def _poll(self):
        try:
            self._apply(self.hub.status())
            self.v["conn"].set("● ao vivo")
        except Exception:
            self.v["conn"].set("● erro")
        self.root.after(800, self._poll)

    def _apply(self, s):
        enabled = s.get("enabled")
        self.v["toggle"].set("MITIGAÇÃO: LIGADA  ●" if enabled else "MITIGAÇÃO: DESLIGADA")
        self.toggle_btn.configure(bg=ON if enabled else OFF, fg="#06210f" if enabled else TXT)

        t = s.get("telemetry", {}) or {}
        o, n, saved = t.get("last_original_ms"), t.get("last_reduced_ms"), t.get("last_saved_ms")
        if o is not None:
            self.v["cut"].set(f"{n} ms  ←  {o} ms" if n is not None else f"{o} ms")
            self.v["saved"].set(f"você economizou {saved} ms" if saved else "")
        else:
            self.v["cut"].set("aguardando combate")
            self.v["saved"].set("")
        self.v["acts"].set(str(t.get("total_actions", 0)))
        self.v["saved_tot"].set(f"{t.get('total_saved_ms', 0)} ms")

        pg = s.get("ping", {}) or {}
        felt = pg.get("felt_p50_ms")
        felt = round(felt) if felt is not None else t.get("last_rtt_ms")
        self.v["ping"].set(f"{felt} ms" if felt is not None else "—")
        wan = pg.get("wan_ms")
        self.v["wan"].set(f"{round(wan)} ms" if wan is not None else "—")
        jit = pg.get("jitter_ms")
        self.v["jit"].set(f"{round(jit)} ms" if jit is not None else "—")
        if jit is None:
            self.jit_label.configure(fg=MUTED)
        elif jit < 25:
            self.jit_label.configure(fg=ON)
        elif jit < 60:
            self.jit_label.configure(fg=WARN)
        else:
            self.jit_label.configure(fg=BAD)
        retr = pg.get("retrans")
        if retr:
            self.v["netnote"].set(f"⚠ {retr} retransmissão(ões) agora — perda na linha.")
        else:
            self.v["netnote"].set("O ping ao NA é física; o que importa é a estabilidade.")

        info = s.get("info", {}) or {}
        sip, sreg = info.get("server_ip"), info.get("server_region")
        self.v["net_title"].set(f"REDE   ·   {sreg} {sip}" if sip else "REDE")

        cfg = s.get("config", {}) or {}
        ms = cfg.get("extra_delay_ms")
        if ms is not None:
            self.v["margin_val"].set(f"{ms} ms")
            if not self.margin.get() == ms and not str(self.root.focus_get()).endswith("scale"):
                self._building_margin = True
                self.margin.set(ms)
                self._building_margin = False
        if "qos" in cfg:
            self.qos_var.set(1 if cfg["qos"] else 0)

        # banner de reinício
        if info.get("reboot_pending"):
            self.reboot_frame.pack(fill="x", padx=14, pady=(0, 10), before=self.toggle_btn)
        else:
            self.reboot_frame.pack_forget()

        # checklist
        self._check("admin", info.get("admin"), "ok", "rode como Admin")
        self._check("routing", info.get("routing"), "ligado", "reinicie o PC")
        oc = info.get("opcodes_count", 0)
        if oc and info.get("opcodes_matched") is not False:
            self._set_check("opcodes", ON, info.get("opcodes_date") or "carregado")
        elif oc and info.get("opcodes_matched") is False and s.get("flows"):
            self._set_check("opcodes", BAD, "não cobre seu servidor")
        else:
            self._set_check("opcodes", WARN if oc else FAINT, "carregado" if oc else "—")
        if info.get("oodle_loaded"):
            self._set_check("oodle", ON, "carregado")
        elif info.get("oodle_missing"):
            self._set_check("oodle", BAD, "falta ffxiv_dx11.exe")
        else:
            self._set_check("oodle", FAINT, "—")
        ga = info.get("game_active", 0)
        if ga:
            self._set_check("ps5", ON, f"{ga} conexão(ões) ativa(s)")
        elif s.get("flows"):
            self._set_check("ps5", WARN, "ocioso")
        else:
            self._set_check("ps5", WARN, "aguardando…")

        self.v["gateway"].set(f"No PS5/PS4: Config. de IP = Manual, Gateway = {self.gateway_ip}"
                              + (f"   |   celular: {self.phone_url}" if self.phone_url else ""))

        # log
        lines = s.get  # noqa
        try:
            log = self.hub.logs(40)
            joined = "\n".join(log)
            if joined != self._last_log:
                self._last_log = joined
                self.logbox.configure(state="normal")
                self.logbox.delete("1.0", "end")
                self.logbox.insert("1.0", joined)
                self.logbox.configure(state="disabled")
                self.logbox.see("end")
        except Exception:
            pass

    def _check(self, key, ok, ok_txt, bad_txt):
        self._set_check(key, ON if ok else BAD, ok_txt if ok else bad_txt)

    def _set_check(self, key, color, txt):
        self.checks[key].configure(fg=color)
        self.v["st_" + key].set(txt)

    def run(self):
        self.root.mainloop()
