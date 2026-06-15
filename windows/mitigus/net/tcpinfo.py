"""
Ping de rede "de graça" no Windows: lê o RTT que o próprio kernel TCP mantém para
um socket conectado, via WSAIoctl(SIO_TCP_INFO). É o MESMO RTT que o controle de
congestionamento usa — medido continuamente do timing dos ACKs reais, sem mandar
nenhum pacote extra e sem precisar de Administrador.

Usamos no socket de SUBIDA do relay (PC -> servidor do FFXIV) pra mostrar no painel
o ping da perna WAN (a "travessia do oceano") e as retransmissões.

TCP_INFO_v0 existe desde o Windows 10 1703 — cobre todo Win10/11. Campos na ordem
EXATA da struct da Microsoft; ULONG64 força alinhamento natural de 8 bytes, então
NÃO usar _pack_.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional

_ULONG = ctypes.c_uint32
_ULONG64 = ctypes.c_uint64
# SOCKET é UINT_PTR (tamanho de ponteiro): 64 bits no Python x64, 32 no x86.
_SOCKET = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

SIO_TCP_INFO = 0xD8000027  # _WSAIORW(IOC_VENDOR, 39)


class TCP_INFO_v0(ctypes.Structure):
    _fields_ = [
        ("State", ctypes.c_int),
        ("Mss", _ULONG),
        ("ConnectionTimeMs", _ULONG64),
        ("TimestampsEnabled", ctypes.c_byte),
        ("RttUs", _ULONG),
        ("MinRttUs", _ULONG),
        ("BytesInFlight", _ULONG),
        ("Cwnd", _ULONG),
        ("SndWnd", _ULONG),
        ("RcvWnd", _ULONG),
        ("RcvBuf", _ULONG),
        ("BytesOut", _ULONG64),
        ("BytesIn", _ULONG64),
        ("BytesReordered", _ULONG),
        ("BytesRetrans", _ULONG),
        ("FastRetrans", _ULONG),
        ("DupAcksIn", _ULONG),
        ("TimeoutEpisodes", _ULONG),
        ("SynRetrans", ctypes.c_ubyte),
    ]


try:
    _ws2 = ctypes.WinDLL("ws2_32", use_last_error=True)
    _WSAIoctl = _ws2.WSAIoctl
    _WSAIoctl.restype = ctypes.c_int
    _WSAIoctl.argtypes = [
        _SOCKET, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD,            # in  buffer (versão)
        ctypes.c_void_p, wintypes.DWORD,            # out buffer (TCP_INFO)
        ctypes.POINTER(wintypes.DWORD),             # bytes retornados
        ctypes.c_void_p, ctypes.c_void_p,           # overlapped, completion (NULL)
    ]
except (OSError, AttributeError):  # não-Windows / sem ws2_32
    _WSAIoctl = None


def query_tcp_info(sock) -> Optional[dict]:
    """RTT/retransmissões do socket conectado, ou None se indisponível.

    `sock` é um socket.socket conectado (ou qualquer objeto com .fileno()).
    Devolve: rtt_ms, min_rtt_ms (piso da rota), bytes_out, bytes_retrans,
    timeout_episodes. Nunca levanta — em erro devolve None.
    """
    if _WSAIoctl is None:
        return None
    try:
        fd = sock.fileno()
    except Exception:
        return None
    if fd is None or fd < 0:
        return None
    info = TCP_INFO_v0()
    version = wintypes.DWORD(0)  # TCP_INFO_v0
    nbytes = wintypes.DWORD(0)
    rc = _WSAIoctl(
        fd, SIO_TCP_INFO,
        ctypes.byref(version), ctypes.sizeof(version),
        ctypes.byref(info), ctypes.sizeof(info),
        ctypes.byref(nbytes), None, None,
    )
    if rc != 0:
        return None
    return {
        "rtt_ms": info.RttUs / 1000.0,
        "min_rtt_ms": info.MinRttUs / 1000.0,
        "bytes_out": int(info.BytesOut),
        "bytes_retrans": int(info.BytesRetrans),
        "timeout_episodes": int(info.TimeoutEpisodes),
    }


if __name__ == "__main__":  # smoke test: liga num host e lê o RTT real
    import socket as _s
    import sys

    host = sys.argv[1] if len(sys.argv) > 1 else "1.1.1.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 443
    c = _s.create_connection((host, port), timeout=5)
    try:
        c.sendall(b"\x00")  # gera ao menos 1 ACK pro kernel ter RTT
    except OSError:
        pass
    print(f"TCP_INFO de {host}:{port} ->", query_tcp_info(c))
    c.close()
