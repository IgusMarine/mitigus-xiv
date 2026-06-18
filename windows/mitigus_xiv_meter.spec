# -*- mode: python ; coding: utf-8 -*-
# Build do DPS METER (variante DPS, branch dps-meter) -> "Mitigus DPS.exe".
# App de CONSOLE que roda o MESMO relay de producao (PS5 -> PC -> servidor),
# desofusca o combate AO VIVO e serve a UI Neon Bars no navegador (porta 8088).
# console=True p/ o amigo ver o status e fechar quando acabar.
#
# Build PRIVADA (enviada direto ao amigo): embute o actions.json (nomes/jobs).
# O ffxiv_dx11.exe (Oodle) NAO vai embutido — o amigo reusa o vendor\ do Mitigus.
import glob
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# tabelas de desofuscacao (.bin) por patch -> _internal/mitigus/deob/data/<ver>/
deob_bins = [(p, os.path.dirname(p)) for p in
             glob.glob("mitigus/deob/data/**/*.bin", recursive=True)]

datas = collect_data_files("pydivert") + deob_bins + [
    ("mitigus/meter/meter.html", "mitigus/meter"),
    ("mitigus/meter/data/actions.json", "mitigus/meter/data"),  # nomes/jobs (gerado)
    ("mitigus/panel/fonts/chakra-petch-latin-400-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus/panel/fonts/chakra-petch-latin-500-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus/panel/fonts/chakra-petch-latin-600-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus/panel/fonts/chakra-petch-latin-700-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus.ico", "."),
]

hiddenimports = (collect_submodules("pydivert") + collect_submodules("mitigus.deob") + [
    "run_proxy",
    "mitigus.meter.server", "mitigus.meter.live", "mitigus.meter.tracker",
    "mitigus.meter.combat", "mitigus.meter.spawn", "mitigus.meter.names",
    "mitigus.oodle.oodle", "mitigus.oodle.locate",
    "mitigus.mitigation.mitigator", "mitigus.capture.recorder",
    "mitigus.panel.server", "mitigus.panel.hub", "mitigus.i18n",
    "mitigus.proxy.divert_nat", "mitigus.proxy.masquerade", "mitigus.proxy.qos",
    "mitigus.net.tcpinfo", "mitigus.net.datacenter", "mitigus.net.socks5",
])

a = Analysis(
    ["run_meter.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["webview", "tkinter", "pystray", "PIL", "clr", "bottle", "proxy_tools"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mitigus DPS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon="mitigus.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Mitigus DPS",
)
