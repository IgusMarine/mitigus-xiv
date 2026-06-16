# -*- mode: python ; coding: utf-8 -*-
# Versão DEFINITIVA: janela FRAMELESS (pywebview/WebView2) -> "Mitigus XIV (app).exe".
# Sem a barra do Windows; barra própria (min/max/fechar) + bandeja. console=False.
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# pywebview: traz WebView2Loader.dll + assemblies .NET + os JS embutidos (lib/js).
webview_datas, webview_binaries, webview_hiddenimports = collect_all("webview")

datas = webview_datas + collect_data_files("pydivert") + [
    ("mitigus/panel/index.html", "mitigus/panel"),
    ("mitigus/panel/fonts/chakra-petch-latin-400-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus/panel/fonts/chakra-petch-latin-500-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus/panel/fonts/chakra-petch-latin-600-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus/panel/fonts/chakra-petch-latin-700-normal.woff2", "mitigus/panel/fonts"),
    ("mitigus.ico", "."),
]

hiddenimports = webview_hiddenimports + collect_submodules("pydivert") + [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr",
    "bottle",
    "proxy_tools",
    "typing_extensions",
    "pystray._win32",
    "PIL.Image",
    "run_proxy",
    "mitigus.oodle.oodle",
    "mitigus.oodle.locate",
    "mitigus.panel.server",
    "mitigus.panel.hub",
    "mitigus.i18n",
    "mitigus.mitigation.mitigator",
    "mitigus.proxy.divert_nat",
    "mitigus.proxy.masquerade",
    "mitigus.proxy.qos",
    "mitigus.net.tcpinfo",
    "mitigus.net.datacenter",
    "mitigus.net.socks5",
]

a = Analysis(
    ["mitigus_window.py"],
    pathex=[],
    binaries=webview_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "webview.platforms.cocoa",
        "webview.platforms.gtk",
        "webview.platforms.qt",
        "webview.platforms.android",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

# ONEDIR (pasta), NÃO onefile: pythonnet/CLR + WebView2 carregam DLLs que nunca
# descarregam -> no onefile a pasta _MEI não some ao sair ("Failed to remove
# temporary directory"). Onedir roda da própria pasta: sem _MEI, sem aviso, e
# inicia mais rápido. O amigo recebe a PASTA (no zip) e roda o .exe de dentro.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mitigus XIV (app)",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
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
    name="Mitigus XIV (app)",
)
