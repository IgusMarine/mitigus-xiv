# Mitigus XIV — Windows native engine

**English** | [Português](README.pt-BR.md)

FFXIV latency mitigation (the "double-weave fix") for **PS5**, running **100% on Windows** — no Linux, no VMs, no Raspberry Pi. This is the evolution of *Weave Box* (the root folder of this repository), which depended on a Linux laptop running `mitigate.py` underneath. Here, the same effect is reconstructed using native packet interception (WinDivert) + a transparent proxy.

> **Status: Phases 0–5 implemented.** Capture (0), transparent proxy (1), opcodes (2), Oodle codec (3), **mitigation (4)**, and **web panel (5)** are ready and covered by tests (26 tests; the mitigation algorithm is validated end-to-end with synthetic bundles, and the PE mapper against `kernel32.dll`). Remaining validation **on hardware**: the WinDivert glue (`divert_nat.py`), the codec against `ffxiv_dx11.exe` (`run_oodle_test.py`), and live mitigation on PS5 (`run_proxy.py --mitigate --panel`).

## How it works (Overview)

```
PS5  --gateway-->  PC Windows  -------->  Router  -->  FFXIV Servers
                       |
                       |  WinDivert (kernel driver) redirects TCP traffic
                       |  Transparent proxy terminates TCP and recovers destination
                       |  Parses bundle/segment/IPC + Oodle decode (Phase 3)
                       |  Mitigation: rewrites animation_lock (Phase 4)
                       |  Oodle re-encode -> forwards
```

FFXIV game traffic is **TCP in plain text** (only compressed), so there is no cryptography to break. The real challenge is **Oodle** (stateful compression per connection since patch 6.3) and putting the PC in the PS5's network path reliably.

## Quickstart (For anyone)

1. Install **Python** (from python.org, marking "Add to PATH").
2. Have `ffxiv_dx11.exe` on your PC — if FFXIV (or the **free trial**) is already installed, Mitigus **finds it automatically**; otherwise, the panel warns you and opens the `windows\vendor\` folder for you to copy the file (see "Adding ffxiv_dx11.exe").
3. **Double-click** **`Iniciar Mitigus XIV.bat`** — it requests Admin privileges automatically, installs missing requirements, enables routing, and opens the panel.
4. On the **panel** (opens in your browser/mobile), follow the **"Connect the PS5"** card — the gateway IP is pre-filled, with a copy button.
5. Turn mitigation on/off and adjust the margin using the panel. Done.

> Just want to see the UI, without a PS5? Double-click **`Painel (demo).bat`**.

## Requirements

- Windows 10/11 x64
- Python 3.11+ (tested on 3.14)
- **Administrator** privileges (WinDivert loads a kernel driver)
- `pydivert` (already packages the signed WinDivert): `pip install -r requirements.txt`

## Quickstart — Phase 0

Open a terminal **as Administrator** in this folder (`windows/`):

```powershell
pip install -r requirements.txt
```

**Option A — Validate the parser with FFXIV on this PC** (most reliable; if you have the PC client / trial installed). Open the game and run:

```powershell
python run_sniff.py --layer network
```

**Option B — Detect the PS5** (the ultimate goal). As Admin:

```powershell
.\setup\enable-routing.ps1          # enables the PC as a router, prints the IP
# configure the PS5 gateway = PC IP (see setup\PS5-SETUP.md)
python run_sniff.py --host <PS5_IP>
```

Success = the block **"FF14ARR detected"** appears and the counters increment (`bundles=`, `comp[oodle=...]`, etc.). In Dawntrail, most bundles are Oodle — they are counted but will only be decoded in Phase 3.

Press `Ctrl+C` to terminate and view the session summary.

## Quickstart — Phase 1 (transparent proxy)

**Validate the local data-path** (no Admin, no WinDivert) — proves the relay + the transform hook where mitigation will occur:

```powershell
python run_proxy.py --demo
```

**Real mode** (Admin; routing enabled and PS5 gateway = this PC):

```powershell
.\setup\enable-routing.ps1
python run_proxy.py --ps5-ip <PS5_IP>
```

It is passthrough: the PS5 should play normally *through* the proxy, and every new stream appears in the log. Mitigation only kicks in at Phase 4 (in the `on_c2s`/`on_s2c` hooks).

Run core unit tests:

```powershell
python -m unittest discover -s tests -v
```

## Quickstart — Phase 3 (Oodle)

Requires `ffxiv_dx11.exe` (x64). Since you are PS5-only, get it by installing the **FFXIV free trial** on a Windows PC (located in the installation's `game\` folder) and copy it to `vendor\ffxiv_dx11.exe`. Then validate the codec:

```powershell
python run_oodle_test.py --exe C:\path\to\ffxiv_dx11.exe
```

Success = `encode/decode Oodle (TCP and UDP) matched`. This confirms the sigscan and the codec — the foundation Phase 4 uses to read/rewrite Dawntrail bundles.

## Quickstart — Phase 4 (mitigation)

Putting it all together: the proxy begins **rewriting `animation_lock_duration`** (restores double-weaving on high latency). As Admin, with routing enabled, the PS5 gateway pointing to the PC, and the `ffxiv_dx11.exe` at hand:

```powershell
python run_proxy.py --ps5-ip <PS5_IP> --mitigate --exe C:\path\to\ffxiv_dx11.exe
```

Opcodes are downloaded/updated automatically (or pass `--opcodes-json`). In the logs, `[mit] S2C_ActionEffect ... wait=600ms->NNNms` shows the lock being trimmed. The safety margin is `--extra-delay 0.075` (do not reduce it). Without `--mitigate`, the proxy runs in passthrough (Phase 1).

## Quickstart — Phase 5 (web panel)

See the UI live **without PS5/Admin** (synthetic telemetry):

```powershell
python run_panel.py        # opens at http://<your-ip>:8080
```

On the real proxy, add `--panel` for the mobile panel (on/off + live latency cuts) accessible from your phone on the same network:

```powershell
python run_proxy.py --ps5-ip <IP> --mitigate --exe <ffxiv_dx11.exe> --panel
```

> The panel listens only on the LAN. **Never** port-forward this port to the internet.

## Structure

```
windows/
├── Iniciar Mitigus XIV.bat   1-click shortcut (auto-Admin + routing + panel)
├── Painel (demo).bat         demo panel shortcut (no PS5/Admin)
├── Build (gerar exe).bat     generates dist\Mitigus XIV App (PyInstaller)
├── mitigus_window.py         .exe entry point (frameless WebView2 window + tray)
├── mitigus_xiv_native.spec   PyInstaller spec (app build, onedir)
├── mitigus.ico               app icon (generated by tools/make_icon.py)
├── run_sniff.py              Phase 0 entry point (sniffer)
├── run_proxy.py              Phase 1 entry point (transparent proxy)
├── update_opcodes.py         downloads/updates definitions.json (Phase 2)
├── run_oodle_test.py         validates Oodle against ffxiv_dx11.exe (Phase 3)
├── run_panel.py              demo web panel (Phase 5, no PS5/Admin)
├── requirements.txt          pydivert & window dependencies
├── mitigus/
│   ├── paths.py              paths (source vs compiled .exe modes)
│   ├── protocol/
│   │   ├── headers.py        ctypes structs + magic (port of mitigate.py)
│   │   ├── bundle.py         stream reassembler + decode (zlib/none)
│   │   ├── opcodes.py        OpcodeDefinition + loader (XivAlexander source)
│   │   └── ipc.py            IPC payload structs (ActionEffect, etc.) + constants
│   ├── net/
│   │   ├── ports.py          FFXIV port ranges + WinDivert filter
│   │   └── adapters.py       Admin checks + LAN IP detection
│   ├── capture/
│   │   └── sniffer.py        SNIFF capture (read-only)
│   ├── proxy/
│   │   ├── conntrack.py      (PS5)->(server) map: the missing SO_ORIGINAL_DST
│   │   ├── relay.py          asyncio relay terminating TCP (hooks/processor)
│   │   └── divert_nat.py     WinDivert userland NAT (DNAT/SNAT)
│   ├── oodle/
│   │   ├── pe.py             manual x64 PE mapper (tested vs kernel32)
│   │   ├── oodle.py          sigscan + Oodle codec (native call, no thunks)
│   │   └── locate.py         finds ffxiv_dx11.exe (SE installer + Steam paths)
│   ├── mitigation/
│   │   ├── stats.py          NumericStatisticsTracker + PendingAction
│   │   └── mitigator.py      animation_lock rewrite + double-weaving (Phase 4)
│   └── panel/
│       ├── hub.py            ControlHub (on/off + telemetry, thread-safe)
│       ├── server.py         HTTP dashboard server (stdlib)
│       └── index.html        Mobile UI (on/off + live metric display)
├── tests/                    26 tests (mitigation, panel, PE, opcodes, relay, conntrack)
└── setup/
    ├── enable-routing.ps1    PC becomes router (IP forwarding, no ICS/NAT)
    ├── disable-routing.ps1   reverts routing changes
    └── PS5-SETUP.md          Static IP + gateway setup on PS5
```

## Roadmap

- **Phase 0 — Capture:** see FFXIV packets from PS5. ✅ Implemented
- **Phase 1 — Transparent proxy:** WinDivert redirects traffic to a local listener; `asyncio` relay terminates TCP and opens upstream socket (resolves seq/ack and single-NIC return path). ✅ Core (conntrack+relay) tested; ⏳ WinDivert integration (`divert_nat.py`) to validate on hardware.
- **Phase 2 — Opcodes:** `OpcodeDefinition` (faithful port) + cross-platform loader/updater from XivAlexander source (`update_opcodes.py`). ✅ Implemented and tested
- **Phase 3 — Oodle:** manual PE mapper (`pe.py`, ✅ tested vs kernel32) + per-channel sigscan and codec (`oodle.py`, native call — no Linux ABI thunks). ⏳ Validate codec against `ffxiv_dx11.exe` (`run_oodle_test.py`).
- **Phase 4 — Mitigation:** `PendingAction` by sequence, match ActionRequest↔Effect, rewrite `animation_lock_duration` (margin `extra_delay=0.075` — do not decrease), double-weaving gating, custom OriginalWaitTime IPC. ✅ Implemented and tested (synthetic bundles); ⏳ Validate live on PS5 (`run_proxy.py --mitigate`).
- **Phase 5 — Dashboard + UX:** Redesigned mobile UI (on/off, live cuts, margin slider, PS5 connection guide with pre-filled IP, health checklist) + 1-click shortcut (`Iniciar Mitigus XIV.bat`) and optional `--ps5-ip` (auto-detects PS5). ✅ Implemented and tested (29 tests; UI verified via screenshot).
- **Phase 6 — `.exe` packaging:** onefile via PyInstaller (`Build (gerar exe).bat`), embedding WinDivert driver and panel, UAC manifest (auto-prompts Admin) and frozen-aware paths. Game's `ffxiv_dx11.exe` **is not** packaged (located/provided by user). ✅ Implemented and build validated.
- **Phase 7 — Icon:** original teal crystal (`mitigus.ico`, generated by `tools/make_icon.py`), embedded in the `.exe`. ✅ Done.
- **Phase 8+ — Refining measure_ping (real Windows RTT via SIO_TCP_INFO).**

## Adding ffxiv_dx11.exe

`ffxiv_dx11.exe` is the **game executable** (from Square Enix). The Oodle compression codec lives inside it — without this file, you cannot read Dawntrail packets. For copyright/size reasons, it **is not included in the project**; you provide it (just like the original XivMitm/XivAlexander).

- **If you play on PS5** and don't have the game on PC: install the **FFXIV free trial** (no subscription needed) on any Windows PC. The file resides in `...\FINAL FANTASY XIV - A Realm Reborn\game\ffxiv_dx11.exe`.
- **Auto-detection:** if the game (or trial) is installed, Mitigus finds the `.exe` automatically (checks Square Enix installer and Steam library paths). You don't need to copy anything.
- **If not found:** the panel shows *"missing ffxiv_dx11.exe"* and the folder `windows\vendor\` opens automatically — simply paste the file there and restart.
- Must be the **x64** version (`ffxiv_dx11.exe`, not the legacy `ffxiv.exe`). It **almost never needs replacement** — only the *opcodes* change per patch (which update automatically); Oodle changes very rarely.

## Generating the `.exe` (avoids installing Python on user's PC)

Double-clicking **`Build (gerar exe).bat`** generates the output in `dist\` (~10 MB), which embeds the WinDivert driver and the panel, requests Administrator (UAC), enables routing, and runs the panel:

- **`Mitigus XIV App.exe`** — opens in a **dedicated window** (WebView2/Edge in app mode, falling back to browser if unavailable).
- Check the package without Admin: `"dist\Mitigus XIV App\Mitigus XIV App.exe" --selfcheck`.

## Opcodes (updating per patch)

Opcodes (the IDs indicating "what packet is this") are **scrambled by Square Enix with every patch** — this is the most common point of failure. Mitigus loads them from an external JSON that updates automatically (sourced from XivAlexander), selects the correct table by server IP, and features an **Update button on the dashboard** (displays the patch date in use).

- When FFXIV updates: click **Update** on the dashboard (or run `python update_opcodes.py`). It may take a few hours to 1–2 days for the community to publish opcodes for a major patch.
- Opcodes are **global per patch** (JP/NA/EU = same version = same opcodes; only CN/KR differ). The default table covers **NA/Aether** (range `204.2.29.0/24`), so the default source works out of the box.
- If the dashboard ever shows **"opcodes do not cover your server"**, update or pass a custom file with `--opcodes-json your_file.json`.

## Log / Diagnostics

Every proxy session writes a **`mitigus.log`** (next to the `.exe` / in `windows\`) logging console stdout: `[nat] new flow...`, `[mit] S2C_ActionEffect wait=600ms->NNNms`, and errors. The dashboard also links the log path in the "Event log" card. This file (+ a screenshot of "System status") is what's used to analyze/troubleshoot interception after testing on the PS5.

## Disclaimer (ToS)

Third-party tools reading/modifying FFXIV traffic violate Square Enix's User Agreement (specifically the "packet spoofing" category, highlighted as a priority in 2022). There is no kernel-level anti-cheat and enforcement is reactive, but the risk **is not zero** and the decision is yours regarding your own account. This project is for technical/educational purposes.

## Credits

- [XivMitmLatencyMitigator](https://github.com/Soreepeong/XivMitmLatencyMitigator) and [XivAlexander](https://github.com/Soreepeong/XivAlexander) (Soreepeong) — the mitigation technique and source of opcodes.
- [WinDivert](https://github.com/basil00/WinDivert) (basil00) — userland packet interception on Windows.
- [Chakra Petch](https://fonts.google.com/specimen/Chakra+Petch) font (SIL OFL 1.1).
