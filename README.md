# Mitigus XIV

**English** | [Português](README.pt-BR.md)

**FINAL FANTASY XIV** latency mitigator 100% native on **Windows**, designed for playing on **consoles (PS5/PS4)** — where plugins and addons do not exist.

It does what [XivMitmLatencyMitigator](https://github.com/Soreepeong/XivMitmLatencyMitigator) / [XivAlexander](https://github.com/Soreepeong/XivAlexander) do (subtracting network RTT from the `animation_lock_duration` so you can double-weave perfectly), but **without Linux, without VMs, and without modifying the console**: the PC becomes the console's gateway, intercepting FFXIV network traffic and correcting the lock in real-time.

```
  PS5/PS4  ──gateway──►  PC (Windows)  ──►  Router  ──►  FFXIV Servers
                              │
                              ├─ masquerades (NAT) the console's general internet traffic
                              ├─ redirects ONLY FFXIV connections to a local proxy
                              ├─ decodes (Oodle) and cuts the animation lock
                              └─ dashboard (native window + http://IP:8080 on mobile)
```

## How it works
- The console points its **gateway** to the PC. Windows forwards the traffic; Mitigus applies NAT for general internet traffic and **redirects only FFXIV connections** to a local proxy.
- The proxy terminates the TCP connection, decodes the packets (using Oodle, loaded from `ffxiv_dx11.exe`), and rewrites the `animation_lock_duration` by subtracting the measured RTT — with an adjustable safety margin (NoClippy-style / adaptive).
- A **dashboard** (frameless native window via WebView2, also accessible on mobile) displays real-time animation lock reductions, ping (network vs. game), jitter, and system status.

## Requirements
- **Windows 10/11** (x64). Must run as **Administrator** (loads the WinDivert kernel driver).
- **`ffxiv_dx11.exe`** — required for Oodle decompression. **NOT included in the package (copyrighted).** You can get it from the **free trial** of FFXIV on any Windows PC and place it in the Mitigus folder (or under `vendor\`). The app automatically opens the folder and warns you if it is missing.
- Console and PC on the **same local network** (PC on wired Ethernet recommended).
- Windows needs to be **restarted once** after enabling internet sharing (the app will prompt you).

## How to use
1. Extract the **"Mitigus XIV App"** folder and place your `ffxiv_dx11.exe` inside it.
2. Run **"Mitigus XIV App.exe"** (accept the Administrator / UAC prompt).
3. On the console: **Network → Set Up Internet Connection → Custom/Manual** and point the **Gateway** to the PC's IP address (the dashboard will show this IP). Set primary DNS to `1.1.1.1`.
4. Open FFXIV. The dashboard will show live latency mitigation metrics. Access from your phone (on the same network) at: `http://PC_IP:8080`.

## Build (from source)
```bash
cd windows
pip install -r requirements.txt
python -m PyInstaller mitigus_xiv_native.spec   # generates dist/"Mitigus XIV App"/
python -m unittest discover -s tests            # tests
```
Technical documentation and other running modes (console/window/tray) can be found in [`windows/README.md`](windows/README.md).

## Maintenance
- The game's opcodes shuffle with **every game patch** — Mitigus attempts to auto-update them on launch (using the same source as XivAlexander); there is also an **Update** button on the dashboard.
- During major patches, remember to replace `ffxiv_dx11.exe` with the one from the updated game client.

## ⚠️ Disclaimer (Read before using)
- Unofficial tool, not affiliated with or endorsed by Square Enix / FINAL FANTASY XIV. FINAL FANTASY is a registered trademark of Square Enix.
- **Grey area of the Terms of Service.** Use at your own risk. While it adjusts animation lock client-side and maintains a safety buffer, the risk of account penalties is **not zero**.
- This fixes the **animation lock/weaving**, not physical ping. Character movement, mechanics, and server-side damage snapshots remain subject to your real network latency.
- Provided **without any warranty**.

## Credits
- [XivMitmLatencyMitigator](https://github.com/Soreepeong/XivMitmLatencyMitigator) and [XivAlexander](https://github.com/Soreepeong/XivAlexander) (Soreepeong) — the mitigation technique and source of opcodes.
- [WinDivert](https://github.com/basil00/WinDivert) (basil00) — userland packet interception on Windows.
- [Chakra Petch](https://fonts.google.com/specimen/Chakra+Petch) font (SIL OFL 1.1).
