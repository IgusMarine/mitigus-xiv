# -*- mode: python ; coding: utf-8 -*-
# Versão SEM console do Mitigus XIV: roda em segundo plano com ícone na bandeja.
# console=False (nenhuma janela preta). Inclui pystray + Pillow e o mitigus.ico.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("pydivert") + [
    ("mitigus/panel/index.html", "mitigus/panel"),
    ("mitigus.ico", "."),  # imagem do ícone da bandeja
]

hiddenimports = (
    collect_submodules("pydivert")
    + collect_submodules("pystray")
    + [
        "pystray._win32",
        "PIL.Image",
        "run_proxy",
        "mitigus.oodle.oodle",
        "mitigus.oodle.locate",
        "mitigus.panel.server",
        "mitigus.panel.hub",
        "mitigus.mitigation.mitigator",
        "mitigus.proxy.divert_nat",
        "mitigus.proxy.masquerade",
        "mitigus.proxy.qos",
        "mitigus.net.tcpinfo",
        "mitigus.net.datacenter",
        "mitigus.net.socks5",
    ]
)

a = Analysis(
    ["mitigus_app_tray.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Mitigus XIV (sem console)",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon="mitigus.ico",
)
