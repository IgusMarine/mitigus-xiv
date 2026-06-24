"""
Auto-update do Mitigus, em DUAS camadas (best-effort, nunca derruba o app):

  Camada 1 — DADOS: no boot, busca o `manifest.json` do repo GitHub (publico) e
    baixa pro %LOCALAPPDATA%\\Mitigus\\ o que mudou:
      - deob: `versions.json` (constantes) + as 6 `.bin` da versao do manifest;
      - `buffs.json` (tabela de buffs do rDPS/aDPS);
      - `index.html` (UI do painel).
    Os loaders ja PREFEREM o LOCALAPPDATA (deob/loader.py, constants.py, tracker,
    panel/server), entao o que e baixado vale no proximo boot. Assim, depois de um
    patch, basta `git push` no repo que o app do usuario aplica sozinho.

  Camada 2 — APP: compara a versao deste app (mitigus.__version__) com a do
    manifest; se houver build novo, baixa o .zip pro staging e aplica no PROXIMO
    boot (um .bat destacado espera o exe fechar, copia por cima e reabre — no
    Windows o exe rodando nao pode se sobrescrever). Preserva `vendor\\` e o
    `definitions.json` (copia por cima, sem espelhar/apagar extras).

Tudo e tolerante a falha: sem internet, manifest invalido ou erro de I/O, mantem
o que ja existe e segue. Nada aqui bloqueia o relay/weave.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

from .. import __version__
from ..paths import app_dir, is_frozen

# Repo/branch publico de onde o app puxa manifest + dados. Trocar aqui se mudar.
_REPO = "IgusMarine/mitigus-xiv"
_BRANCH = "dps-meter"
_RAW = f"https://raw.githubusercontent.com/{_REPO}/{_BRANCH}/windows"
MANIFEST_URL = f"{_RAW}/update/manifest.json"

_DEOB_BINS = ("table0.bin", "table1.bin", "table2.bin",
              "midtable.bin", "daytable.bin", "opcodekeytable.bin")

# flags do CreateProcess p/ destacar o .bat do swap (sem janela, vida propria)
_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


# ---- infra -----------------------------------------------------------------
def _mitigus_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Mitigus")


def _update_dir() -> str:
    return os.path.join(_mitigus_dir(), "update")


def _http_get(url: str, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mitigus-xiv-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _vtuple(v) -> tuple:
    """'0.3.0' / '2026.06.18.0000.0000' -> tupla de ints p/ comparar por valor."""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except (ValueError, AttributeError):
        return ()


def _read_state() -> dict:
    try:
        with open(os.path.join(_update_dir(), "state.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    try:
        os.makedirs(_update_dir(), exist_ok=True)
        with open(os.path.join(_update_dir(), "state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


def fetch_manifest(timeout: float = 30.0) -> dict:
    """Baixa e parseia o manifest do repo. Levanta em erro (o chamador trata)."""
    data = json.loads(_http_get(MANIFEST_URL, timeout).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest nao e um objeto JSON")
    return data


# ---- Camada 1: dados -------------------------------------------------------
def sync_data(manifest: dict, log=lambda m: None) -> list:
    """Baixa pro LOCALAPPDATA os dados que mudaram. Cada item e independente e
    best-effort (um falhar nao impede os outros). Devolve a lista do que mudou."""
    base = _mitigus_dir()
    state = _read_state()
    changed = []

    dv = manifest.get("deob_version")
    if dv:
        try:
            if _sync_deob(manifest, dv, base, log) or state.get("deob_version") != dv:
                changed.append(f"deob {dv}")
            state["deob_version"] = dv
        except Exception as e:
            log(f"update: deob falhou: {e}")

    if _sync_rev_file(manifest, "buffs", manifest.get("buffs_url"),
                      os.path.join(base, "meter", "buffs.json"), state, log):
        changed.append("buffs")

    if _sync_rev_file(manifest, "ui", manifest.get("ui_url"),
                      os.path.join(base, "ui", "index.html"), state, log):
        changed.append("ui")

    _write_state(state)
    return changed


def _sync_deob(manifest, version, base, log) -> bool:
    """versions.json (constantes) sempre; as 6 .bin so se ainda nao tiver.
    Devolve True se baixou as .bin desta versao agora."""
    deob = os.path.join(base, "deob")
    os.makedirs(deob, exist_ok=True)
    vurl = manifest.get("deob_constants_url")
    if vurl:
        data = _http_get(vurl)
        json.loads(data.decode("utf-8"))  # valida antes de gravar
        with open(os.path.join(deob, "versions.json"), "wb") as f:
            f.write(data)

    vdir = os.path.join(deob, "data", version)
    if all(os.path.exists(os.path.join(vdir, b)) for b in _DEOB_BINS):
        return False
    baseurl = manifest.get("deob_base_url")
    if not baseurl:
        return False
    tmp = vdir + ".part"
    os.makedirs(tmp, exist_ok=True)
    for b in _DEOB_BINS:
        data = _http_get(f"{baseurl.rstrip('/')}/{version}/{b}")
        with open(os.path.join(tmp, b), "wb") as f:
            f.write(data)
    # so promove quando TODAS baixaram (evita versao meia-baixada)
    if os.path.isdir(vdir):
        shutil.rmtree(vdir, ignore_errors=True)
    os.replace(tmp, vdir)
    log(f"update: tabelas deob {version} baixadas")
    return True


def _sync_rev_file(manifest, key, url, dest, state, log) -> bool:
    """Baixa `url` -> `dest` se o rev do manifest for novo (ou o arquivo sumiu)."""
    rev = manifest.get(f"{key}_rev")
    if not url or rev is None:
        return False
    if state.get(f"{key}_rev") == rev and os.path.exists(dest):
        return False
    try:
        data = _http_get(url)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        state[f"{key}_rev"] = rev
        log(f"update: {key} atualizado (rev {rev})")
        return True
    except Exception as e:
        log(f"update: {key} falhou: {e}")
        return False


# ---- Camada 2: app --------------------------------------------------------
def app_update_available(manifest: dict) -> bool:
    latest = manifest.get("app_version")
    return bool(latest) and _vtuple(latest) > _vtuple(__version__)


def stage_app_update(manifest: dict, log=lambda m: None) -> bool:
    """Baixa o zip do build novo e extrai pro staging; marca ready.json.
    Retorna True se ficou pronto p/ aplicar no proximo boot."""
    url = manifest.get("app_zip_url")
    ver = manifest.get("app_version")
    if not url or not ver:
        return False
    up = _update_dir()
    try:
        os.makedirs(up, exist_ok=True)
        zpath = os.path.join(up, "app.zip")
        staged = os.path.join(up, "staged")
        data = _http_get(url, timeout=600)
        with open(zpath, "wb") as f:
            f.write(data)
        if os.path.isdir(staged):
            shutil.rmtree(staged, ignore_errors=True)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(staged)
        os.remove(zpath)
        appfolder = _find_app_folder(staged)
        if not appfolder:
            log("update: zip do build sem a pasta do app (com .exe)")
            return False
        with open(os.path.join(up, "ready.json"), "w", encoding="utf-8") as f:
            json.dump({"version": ver, "app_folder": appfolder, "target": app_dir()}, f)
        log(f"update: build {ver} baixado, sera aplicado no proximo boot")
        return True
    except Exception as e:
        log(f"update: download do build falhou: {e}")
        return False


def _find_app_folder(staged: str):
    """Acha a pasta do build onedir dentro do staging (a que tem um .exe)."""
    try:
        entries = os.listdir(staged)
    except OSError:
        return None
    if any(f.lower().endswith(".exe") for f in entries):
        return staged
    for entry in entries:
        p = os.path.join(staged, entry)
        if os.path.isdir(p):
            try:
                if any(f.lower().endswith(".exe") for f in os.listdir(p)):
                    return p
            except OSError:
                pass
    return None


def apply_pending_update(log=lambda m: None) -> bool:
    """No boot (so quando frozen): se ha build novo no staging, dispara o swap via
    .bat destacado e devolve True p/ o app SAIR imediatamente (pro .bat copiar por
    cima com o exe fechado). Sem staging valido, devolve False e o app segue normal."""
    if not is_frozen():
        return False
    ready = os.path.join(_update_dir(), "ready.json")
    if not os.path.exists(ready):
        return False
    try:
        with open(ready, encoding="utf-8") as f:
            info = json.load(f)
        ver = info.get("version")
        src = info.get("app_folder")
        target = info.get("target") or app_dir()
        exe_name = os.path.basename(sys.executable)
        # ja estamos na versao nova (swap ja aconteceu) -> limpa e segue
        if not ver or _vtuple(ver) <= _vtuple(__version__):
            os.remove(ready)
            return False
        if not (src and os.path.isdir(src) and os.path.exists(os.path.join(src, exe_name))):
            log("update: staging invalido; ignorando")
            os.remove(ready)
            return False
        _spawn_swap(src, target, exe_name, log)
        return True
    except Exception as e:
        log(f"update: apply falhou: {e}")
        return False


def _spawn_swap(src: str, target: str, exe_name: str, log) -> None:
    """Escreve e dispara o .bat que: espera este processo fechar, copia o build
    novo por cima (sem apagar vendor/definitions), reabre o app e se autoexclui."""
    pid = os.getpid()
    up = _update_dir()
    bat = os.path.join(up, "apply.bat")
    exe_path = os.path.join(target, exe_name)
    lines = [
        "@echo off",
        "setlocal",
        ":wait",
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && '
        f'(ping -n 2 127.0.0.1 >nul & goto wait)',
        # /E copia subpastas (inclui _internal); SEM /MIR -> nao apaga vendor/definitions
        f'robocopy "{src}" "{target}" /E /R:3 /W:2 /NFL /NDL /NJH /NJS /NP >nul',
        f'start "" "{exe_path}"',
        f'rmdir /S /Q "{os.path.join(up, "staged")}" 2>nul',
        f'del "{os.path.join(up, "ready.json")}" 2>nul',
        'del "%~f0"',
    ]
    with open(bat, "w", encoding="ascii", errors="replace", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    subprocess.Popen(["cmd", "/c", bat], creationflags=_DETACHED,
                     close_fds=True, cwd=up)
    log("update: aplicando build novo... o app vai reabrir sozinho.")
