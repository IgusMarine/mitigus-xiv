# -*- mode: python ; coding: utf-8 -*-
# Empacota o Mitigus XIV num .exe único (onefile), pedindo Administrador (UAC).
# Inclui o driver do WinDivert (do pydivert) e o index.html do painel.
# NÃO inclui o ffxiv_dx11.exe do jogo — esse é fornecido pelo usuário em runtime.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("pydivert") + [("mitigus/panel/index.html", "mitigus/panel")]

hiddenimports = collect_submodules("pydivert") + [
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

a = Analysis(
    ["mitigus_app.py"],
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
    name="Mitigus XIV",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon="mitigus.ico",
)
