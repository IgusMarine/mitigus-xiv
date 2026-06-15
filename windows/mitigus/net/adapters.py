"""Utilitários de ambiente: checagem de Administrador e IP local da LAN."""
from __future__ import annotations

import ctypes
import os
import socket
import time
from typing import Optional


def is_admin() -> bool:
    """True se o processo tem privilégios de Administrador (WinDivert exige)."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def primary_ipv4() -> Optional[str]:
    """IPv4 da interface usada para sair à internet (candidato a gateway do PS5)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def routing_enabled() -> bool:
    """True se o IP forwarding (PC como roteador) está ligado no registro."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"
        ) as key:
            val, _ = winreg.QueryValueEx(key, "IPEnableRouter")
            return int(val) == 1
    except (OSError, ValueError):
        return False


def remoteaccess_running() -> bool:
    """True se o serviço RemoteAccess (roteamento) está rodando."""
    try:
        import subprocess

        out = subprocess.run(
            ["sc", "query", "RemoteAccess"], capture_output=True, text=True, timeout=10
        ).stdout
        return "RUNNING" in out.upper()
    except Exception:
        return False


def enable_routing() -> bool:
    """
    Liga o IP forwarding (PC como gateway do PS5). Requer Administrador.
    Equivale ao setup\\enable-routing.ps1, mas em Python — para o .exe ser
    autocontido. Best-effort: devolve True se ao menos o registro foi setado.

    Só MARCA "precisa reiniciar" quando REALMENTE liga (0->1). Se já estava ligado,
    não marca nada — então quem já tinha configurado/reiniciado nunca é incomodado.
    """
    was_on = routing_enabled()
    ok = False
    try:
        import winreg

        with winreg.CreateKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"
        ) as key:
            winreg.SetValueEx(key, "IPEnableRouter", 0, winreg.REG_DWORD, 1)
        ok = True
    except OSError:
        pass
    if ok and not was_on:  # acabamos de LIGAR -> aí sim precisa reiniciar
        _write_float(_marker_path(), _boot_time())
    try:
        import subprocess

        subprocess.run(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                "Get-NetIPInterface -AddressFamily IPv4 -ConnectionState Connected | "
                "Set-NetIPInterface -Forwarding Enabled; "
                "Set-Service -Name RemoteAccess -StartupType Automatic; "
                "Start-Service -Name RemoteAccess",
            ],
            capture_output=True,
            timeout=40,
        )
    except Exception:
        pass
    return ok


# ── detecção de reinício pendente ────────────────────────────────────────────
# Marcador num lugar FIXO (%LOCALAPPDATA%) pra não depender da pasta do .exe. Só é
# escrito quando enable_routing LIGA o roteamento (0->1) — então quem já estava
# ligado/reiniciado NUNCA é incomodado. reboot_pending vira False assim que o boot
# muda (reiniciou). A "dispensa" garante: no máximo 1 popup por boot.
def _state_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "MitigusXIV")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return base
    return d


def _marker_path() -> str:
    return os.path.join(_state_dir(), "reboot_marker")


def _dismiss_path() -> str:
    return os.path.join(_state_dir(), "reboot_dismissed")


def _boot_time() -> float:
    """Hora (epoch) do último boot do Windows, via GetTickCount64 (uptime)."""
    try:
        ms = ctypes.windll.kernel32.GetTickCount64()
        return time.time() - ms / 1000.0
    except Exception:
        return 0.0


def _read_float(path: str) -> Optional[float]:
    try:
        with open(path, encoding="utf-8") as fh:
            return float(fh.read().strip())
    except (OSError, ValueError):
        return None


def _write_float(path: str, val: float) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(val))
    except OSError:
        pass


def _reboot_pending_decide(routing_on: bool, marker_boot: Optional[float],
                           current_boot: float, tol: float = 120.0) -> bool:
    """Lógica pura (testável): pendente se o roteamento está ligado, EXISTE um marcador
    (ou seja, NÓS ligamos o roteamento) e a sessão de boot atual é a mesma da marcação
    (ainda não reiniciou). Sem marcador = já estava ligado = não pendente."""
    if not routing_on or marker_boot is None:
        return False
    return abs(current_boot - marker_boot) <= tol


def reboot_pending() -> bool:
    """True se ESTE programa ligou o roteamento e o Windows ainda não reiniciou desde
    então. Se já estava ligado (sem marcador), devolve False — não incomoda ninguém.
    Limpa o marcador automaticamente quando detecta que já reiniciou."""
    if not routing_enabled():
        return False
    marker = _read_float(_marker_path())
    if not _reboot_pending_decide(True, marker, _boot_time()):
        if marker is not None:
            try:
                os.remove(_marker_path())  # boot mudou -> reiniciou -> tudo certo
            except OSError:
                pass
        return False
    return True


def mark_reboot_dismissed() -> None:
    """Registra que o usuário já viu o aviso de reinício NESTE boot (pra não repetir
    o popup a cada abertura). O aviso passivo (banner) continua."""
    _write_float(_dismiss_path(), _boot_time())


def reboot_should_prompt() -> bool:
    """True = mostrar o POPUP de reinício (pendente E ainda não dispensado neste boot)."""
    if not reboot_pending():
        return False
    dismissed = _read_float(_dismiss_path())
    return not _reboot_pending_decide(True, dismissed, _boot_time())


def ask_yes_no(title: str, text: str) -> bool:
    """Caixa de diálogo nativa Sim/Não do Windows. True = clicou Sim."""
    try:
        MB_YESNO = 0x4
        MB_ICONQUESTION = 0x20
        MB_SETFOREGROUND = 0x10000
        MB_TOPMOST = 0x40000
        r = ctypes.windll.user32.MessageBoxW(
            0, text, title, MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST)
        return r == 6  # IDYES
    except Exception:
        return False


def reboot_windows(delay: int = 20,
                   message: str = "Reiniciando para ativar o Mitigus XIV...") -> bool:
    """Agenda o reinício do Windows em `delay` segundos (o usuário pode salvar)."""
    try:
        import subprocess
        subprocess.run(["shutdown", "/r", "/t", str(int(delay)), "/c", message], timeout=10)
        return True
    except Exception:
        return False


def open_firewall_port(port: int, name: str = "Mitigus XIV Panel") -> bool:
    """Libera a porta do painel no Firewall do Windows, SÓ pra rede local
    (remoteip=LocalSubnet), pra o celular conseguir abrir o painel. Sem isto o
    Windows bloqueia conexões de entrada de outros aparelhos. Best-effort, idempotente."""
    try:
        import subprocess
        subprocess.run(  # remove regra antiga (evita duplicar / porta velha)
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
            capture_output=True, timeout=15)
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}",
             "dir=in", "action=allow", "protocol=TCP", f"localport={int(port)}",
             "remoteip=LocalSubnet", "profile=any"],
            capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False
