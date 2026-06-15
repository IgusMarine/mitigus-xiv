# -*- mode: python ; coding: utf-8 -*-
# Versão "janela" do Mitigus XIV: abre o painel numa janela do app (Edge --app).
# Mesma engine do .exe normal; muda só o entry (mitigus_app_window.py) e o nome.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("pydivert") + [("mitigus/panel/index.html", "mitigus/panel")]

hiddenimports = collect_submodules("pydivert") + [
    "run_proxy",
    "mitigus_app",
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
    ["mitigus_app_window.py"],
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
    name="Mitigus XIV (janela)",
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
