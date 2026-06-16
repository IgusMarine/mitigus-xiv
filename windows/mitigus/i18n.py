"""
i18n do lado Python (EN/PT/ES).

O painel web tem o próprio dicionário (em index.html); este módulo cobre o que o
usuário vê FORA do navegador: o menu da bandeja, os diálogos nativos (pedido de
reinício, erros) e as mensagens de log que o hub gera (e que aparecem no
"Registro de eventos" do painel).

Fonte única do idioma: o painel manda POST /api/lang quando detecta/troca; o
servidor chama save_lang(), que persiste em settings.json. No próximo arranque
(antes do painel abrir) load_lang() lê esse arquivo pra bandeja/diálogos já
saírem no idioma certo; sem arquivo, cai no idioma do Windows.

Sem dependências externas — stdlib pura, thread-safe.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional

LANGS = ("en", "pt", "es")

_lock = threading.Lock()
_lang = "en"

MESSAGES = {
    "en": {
        "tray.open": "Open panel",
        "tray.quit": "Quit",
        "log.mit_on": "mitigation ON",
        "log.mit_off": "mitigation OFF",
        "log.margin": "safety margin = {ms}ms",
        "log.qos_on": "anti-bufferbloat QoS ON",
        "log.qos_off": "anti-bufferbloat QoS off",
        "log.route": "route = {target}",
        "log.reboot_req": "Windows restart requested from the panel (20s)",
        "dlg.reboot_title": "Mitigus XIV — restart Windows?",
        "dlg.reboot_text": (
            "For your PS5/PS4 to connect (accept the PC as gateway), Windows must "
            "have been restarted ONCE after enabling internet sharing. Without that, "
            "the console gives a network error.\n\n"
            "• If the console ALREADY connects fine, click No.\n"
            "• If you have not tested yet, or got a network error on the console, click Yes.\n\n"
            "Save your open files. Restart now?"
        ),
        "dlg.need_admin": "Administrator required.\nOpen again and accept the Windows prompt (UAC).",
        "dlg.cant_start": (
            "Could not start.\n\nIf the PREVIOUS version of Mitigus is still open "
            "(tray icon, near the clock), close it first: right-click it and choose "
            "'Quit'. Then open this one again.\n\n"
            "Details in the mitigus.log file (next to the program)."
        ),
        "dlg.unexpected": "Unexpected error.\nSee the mitigus.log file.",
    },
    "pt": {
        "tray.open": "Abrir painel",
        "tray.quit": "Sair",
        "log.mit_on": "mitigação LIGADA",
        "log.mit_off": "mitigação DESLIGADA",
        "log.margin": "margem de segurança = {ms}ms",
        "log.qos_on": "QoS anti-bufferbloat LIGADO",
        "log.qos_off": "QoS anti-bufferbloat desligado",
        "log.route": "rota = {target}",
        "log.reboot_req": "reinício do Windows solicitado pelo painel (20s)",
        "dlg.reboot_title": "Mitigus XIV — reiniciar o Windows?",
        "dlg.reboot_text": (
            "Para o seu PS5/PS4 conseguir conectar (aceitar o PC como gateway), o "
            "Windows precisa ter sido reiniciado UMA vez depois de ativar o "
            "compartilhamento de internet. Sem isso, o console dá erro de rede.\n\n"
            "• Se o console JÁ conecta normalmente, clique Não.\n"
            "• Se ainda não testou, ou deu erro de rede no console, clique Sim.\n\n"
            "Salve seus arquivos abertos. Reiniciar agora?"
        ),
        "dlg.need_admin": "Preciso de Administrador.\nAbra de novo e aceite o aviso do Windows (UAC).",
        "dlg.cant_start": (
            "Não consegui iniciar.\n\nSe a versão ANTERIOR do Mitigus ainda estiver "
            "aberta (ícone na bandeja, perto do relógio), feche-a primeiro: clique com "
            "o botão direito nela e em 'Sair'. Depois abra este de novo.\n\n"
            "Detalhes no arquivo mitigus.log (ao lado do programa)."
        ),
        "dlg.unexpected": "Erro inesperado.\nVeja o arquivo mitigus.log.",
    },
    "es": {
        "tray.open": "Abrir panel",
        "tray.quit": "Salir",
        "log.mit_on": "mitigación ACTIVADA",
        "log.mit_off": "mitigación DESACTIVADA",
        "log.margin": "margen de seguridad = {ms}ms",
        "log.qos_on": "QoS anti-bufferbloat ACTIVADO",
        "log.qos_off": "QoS anti-bufferbloat desactivado",
        "log.route": "ruta = {target}",
        "log.reboot_req": "reinicio de Windows solicitado desde el panel (20s)",
        "dlg.reboot_title": "Mitigus XIV — ¿reiniciar Windows?",
        "dlg.reboot_text": (
            "Para que tu PS5/PS4 pueda conectar (aceptar el PC como puerta de enlace), "
            "Windows debe haberse reiniciado UNA vez tras activar el uso compartido de "
            "internet. Sin eso, la consola da error de red.\n\n"
            "• Si la consola YA conecta bien, pulsa No.\n"
            "• Si aún no lo probaste, o dio error de red en la consola, pulsa Sí.\n\n"
            "Guarda tus archivos abiertos. ¿Reiniciar ahora?"
        ),
        "dlg.need_admin": "Se requiere Administrador.\nÁbrelo de nuevo y acepta el aviso de Windows (UAC).",
        "dlg.cant_start": (
            "No se pudo iniciar.\n\nSi la versión ANTERIOR de Mitigus sigue abierta "
            "(icono en la bandeja, cerca del reloj), ciérrala primero: haz clic derecho "
            "y elige 'Salir'. Luego vuelve a abrir este programa.\n\n"
            "Detalles en el archivo mitigus.log (junto al programa)."
        ),
        "dlg.unexpected": "Error inesperado.\nMira el archivo mitigus.log.",
    },
}


def normalize(lang: Optional[str]) -> str:
    """Devolve um código suportado ('en'/'pt'/'es'); o resto vira 'en'."""
    return lang if lang in MESSAGES else "en"


def set_lang(lang: Optional[str]) -> str:
    global _lang
    with _lock:
        _lang = normalize(lang)
        return _lang


def get_lang() -> str:
    with _lock:
        return _lang


def t(key: str, **kw) -> str:
    """Traduz a chave no idioma atual; cai pro inglês e, por fim, pra própria chave."""
    with _lock:
        lang = _lang
    s = MESSAGES.get(lang, {}).get(key)
    if s is None:
        s = MESSAGES["en"].get(key, key)
    if kw:
        try:
            s = s.format(**kw)
        except (KeyError, IndexError, ValueError):
            pass
    return s


def _detect_os_lang() -> str:
    """Idioma do Windows pro primeiro arranque (antes de o painel mandar /api/lang)."""
    try:
        import locale
        code = (locale.getlocale()[0] or "")
        if not code:
            code = (locale.getdefaultlocale()[0] or "")
        code = code.lower()
    except Exception:
        code = ""
    if code.startswith("pt") or "portug" in code:
        return "pt"
    if code.startswith("es") or "spanish" in code:
        return "es"
    return "en"


def _settings_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Mitigus", "settings.json")


def load_lang() -> str:
    """Lê o idioma salvo; sem arquivo, usa o do Windows. Chamar no arranque."""
    try:
        with open(_settings_path(), "r", encoding="utf-8") as fp:
            data = json.load(fp)
        saved = data.get("lang")
        if saved in MESSAGES:
            return set_lang(saved)
    except Exception:
        pass
    return set_lang(_detect_os_lang())


def save_lang(lang: Optional[str]) -> str:
    """Define E persiste o idioma (chamado pelo POST /api/lang do painel)."""
    set_lang(lang)
    try:
        p = _settings_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fp:
            json.dump({"lang": get_lang()}, fp)
    except Exception:
        pass
    return get_lang()
