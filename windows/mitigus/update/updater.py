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

import hashlib
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
            if _sync_deob(manifest, dv, base, log):
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
    """Baixa as 6 .bin da `version` (atomico) e SO DEPOIS grava o versions.json —
    assim o LATEST do loader nunca aponta pra uma versao sem tabelas (o que
    crasharia o deob no boot). Pula se a versao ja e conhecida (embutida no build
    ou ja sincronizada antes). Devolve True se baixou agora."""
    try:
        from ..deob.constants import VERSIONS as _known
        if version in _known:
            return False  # ja vem no build (ou ja sincronizada) -> nada a fazer
    except Exception:
        pass
    baseurl = manifest.get("deob_base_url")
    vurl = manifest.get("deob_constants_url")
    if not baseurl or not vurl:
        return False
    deob = os.path.join(base, "deob")
    vdir = os.path.join(deob, "data", version)
    downloaded = False
    if not all(os.path.exists(os.path.join(vdir, b)) for b in _DEOB_BINS):
        tmp = vdir + ".part"
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        for b in _DEOB_BINS:
            data = _http_get(f"{baseurl.rstrip('/')}/{version}/{b}")
            with open(os.path.join(tmp, b), "wb") as f:
                f.write(data)
        if os.path.isdir(vdir):
            shutil.rmtree(vdir, ignore_errors=True)
        os.replace(tmp, vdir)  # promove so com TODAS as .bin no lugar
        downloaded = True
    # constantes (versions.json) SO depois das .bin -> nunca LATEST sem tabelas.
    # Regrava so quando baixou .bin agora (ou se ainda nao existe) -> idempotente.
    vjson = os.path.join(deob, "versions.json")
    if downloaded or not os.path.exists(vjson):
        data = _http_get(vurl)
        json.loads(data.decode("utf-8"))  # valida antes de gravar
        os.makedirs(deob, exist_ok=True)
        tmpv = vjson + ".part"
        with open(tmpv, "wb") as f:
            f.write(data)
        os.replace(tmpv, vjson)
    if downloaded:
        log(f"update: deob {version} sincronizada")
    return downloaded


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
        want = manifest.get("app_zip_sha256")
        if want:
            got = hashlib.sha256(data).hexdigest()
            if got.lower() != str(want).lower():
                log(f"update: hash do build nao confere (esp {str(want)[:12]}…, "
                    f"veio {got[:12]}…) — abortado")
                return False
        with open(zpath, "wb") as f:
            f.write(data)
        if os.path.isdir(staged):
            shutil.rmtree(staged, ignore_errors=True)
        with zipfile.ZipFile(zpath) as z:
            _safe_extract(z, staged)   # guarda anti zip-slip
        os.remove(zpath)
        appfolder = _find_app_folder(staged)
        exe = _find_exe_name(appfolder) if appfolder else None
        if not appfolder or not exe:
            log("update: zip do build sem a pasta do app (com .exe)")
            return False
        with open(os.path.join(up, "ready.json"), "w", encoding="utf-8") as f:
            json.dump({"version": ver, "app_folder": appfolder,
                       "target": app_dir(), "exe": exe}, f)
        log(f"update: build {ver} baixado, sera aplicado no proximo boot")
        return True
    except Exception as e:
        log(f"update: download do build falhou: {e}")
        return False


def _safe_extract(z: zipfile.ZipFile, dest: str) -> None:
    """extractall com guarda contra zip-slip (entrada que escaparia de `dest`)."""
    dest_abs = os.path.abspath(dest)
    for member in z.namelist():
        target = os.path.abspath(os.path.join(dest, member))
        if target != dest_abs and not target.startswith(dest_abs + os.sep):
            raise ValueError(f"entrada de zip suspeita (zip-slip): {member}")
    z.extractall(dest)


def _find_exe_name(appfolder: str):
    try:
        for f in os.listdir(appfolder):
            if f.lower().endswith(".exe"):
                return f
    except OSError:
        pass
    return None


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
        exe_name = info.get("exe") or os.path.basename(sys.executable)
        # ja estamos na versao nova (swap ja aconteceu) -> limpa e segue
        if not ver or _vtuple(ver) <= _vtuple(__version__):
            os.remove(ready)
            return False
        # seguranca: o staging TEM que estar dentro do nosso update dir — um
        # ready.json adulterado nao pode fazer o robocopy copiar de outro lugar.
        up_abs = os.path.abspath(_update_dir())
        src_abs = os.path.abspath(src) if src else ""
        if not (src_abs == up_abs or src_abs.startswith(up_abs + os.sep)):
            log("update: app_folder fora do update dir; ignorando")
            os.remove(ready)
            return False
        if not (os.path.isdir(src_abs) and os.path.exists(os.path.join(src_abs, exe_name))):
            log("update: staging invalido; ignorando")
            os.remove(ready)
            return False
        _spawn_swap(src_abs, target, exe_name, log)
        return True
    except Exception as e:
        log(f"update: apply falhou: {e}")
        return False


def _spawn_swap(src: str, target: str, exe_name: str, log) -> None:
    """Escreve e dispara o .bat que: espera este processo fechar, copia o build
    novo por cima (sem apagar vendor/definitions), reabre o app e se autoexclui."""
    pid = os.getpid()
    main_exe = os.path.basename(sys.executable)
    up = _update_dir()
    bat = os.path.join(up, "apply.bat")
    exe_path = os.path.join(target, exe_name)
    ffxiv = os.path.join(target, "ffxiv_dx11.exe")
    lines = [
        "@echo off",
        "setlocal",
        "set /a tries=0",
        ":wait",
        # segue p/ o swap quando o PRINCIPAL sumir (confere PID *e* nome, robusto a
        # PID reciclado); teto de ~120 tentativas (~6 min) p/ nunca travar p/ sempre.
        f'tasklist /FI "PID eq {pid}" /FI "IMAGENAME eq {main_exe}" 2>nul '
        f'| find /I "{main_exe}" >nul || goto doswap',
        "set /a tries+=1",
        "if %tries% geq 120 goto doswap",
        "ping -n 3 127.0.0.1 >nul",
        "goto wait",
        ":doswap",
        # /E copia subpastas (inclui _internal); SEM /MIR -> preserva vendor/definitions
        f'robocopy "{src}" "{target}" /E /R:3 /W:2 /NFL /NDL /NJH /NJS /NP >nul',
        f'del "{ffxiv}" 2>nul',  # hardlink antigo do GPN -> recriado no proximo boot
        f'if exist "{exe_path}" start "" "{exe_path}"',
        f'rmdir /S /Q "{os.path.join(up, "staged")}" 2>nul',
        f'del "{os.path.join(up, "ready.json")}" 2>nul',
        'del "%~f0"',
    ]
    with open(bat, "w", encoding="ascii", errors="replace", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    subprocess.Popen(["cmd", "/c", bat], creationflags=_DETACHED,
                     close_fds=True, cwd=up)
    log("update: aplicando build novo... o app vai reabrir sozinho.")
