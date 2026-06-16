# -*- mode: python ; coding: utf-8 -*-
# Build de CAPTURA (variante DPS, branch dps-meter) -> "Mitigus Captura.exe".
# App de CONSOLE: roda o MESMO relay de producao + grava os segmentos IPC
# pos-Oodle num .jsonl para desofuscacao offline. NAO usa webview/bandeja
# (mais enxuto). console=True para o amigo ver o status e fechar quando acabar.
# O painel web (porta 8080) continua disponivel para ele conferir no celular.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("pydivert") + [
    ("mitigus/panel/index.html", "mitigus/panel"),
    ("mitigus/panel/fonts/chakra-petch-latin-400-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus/panel/fonts/chakra-petch-latin-500-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus/panel/fonts/chakra-petch-latin-600-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus/panel/fonts/chakra-petch-latin-700-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus.ico", "."),
]

hiddenimports = collect_submodules("pydivert") + [
    "run_proxy",
    "mitigus.oodle.oodle",
    "mitigus.oodle.locate",
    "mitigus.panel.server",
    "mitigus.panel.hub",
    "mitigus.i18n",
    "mitigus.mitigation.mitigator",
    "mitigus.capture.recorder",   # import tardio dentro de _run_full
    "mitigus.proxy.divert_nat",
    "mitigus.proxy.masquerade",
    "mitigus.proxy.qos",
    "mitigus.net.tcpinfo",
    "mitigus.net.datacenter",
    "mitigus.net.socks5",
]

a = Analysis(
    ["run_capture.py"],
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

# ONEDIR (pasta), igual ao app de producao: o amigo recebe a PASTA no zip e roda
# o .exe de dentro.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mitigus Captura",
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
    name="Mitigus Captura",
)
