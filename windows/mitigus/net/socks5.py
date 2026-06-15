"""
Cliente SOCKS5 mínimo (no-auth) — pra rotear SÓ o upstream do relay (PC->servidor
do FFXIV) por um VPS, opcional. Como o relay TERMINA o TCP, dá pra mandar só essa
perna pelo túnel, sem tocar no resto da rede do PS5 nem no NAT validado.

É TCP-sobre-TCP? Não: o SOCKS5 só faz o CONNECT inicial; depois o stream é direto
pelo proxy (o VPS reabre a conexão real ao servidor). Por isso preferimos SOCKS5 a
um túnel SSH (que empilha TCP e piora a cauda sob perda).

Sem dependência externa: ~50 linhas. Off por padrão; só liga se o usuário apontar
um VPS no painel.
"""
from __future__ import annotations

import asyncio
import socket
import struct
from typing import Tuple


def build_connect_request(host: str, port: int) -> bytes:
    """Monta o pacote CONNECT do SOCKS5 (testável). IPv4 literal vira ATYP=1; senão
    manda como domínio (ATYP=3)."""
    try:
        addr = b"\x01" + socket.inet_aton(host)      # IPv4
    except OSError:
        h = host.encode("idna") if host else b""
        addr = b"\x03" + bytes([len(h)]) + h          # domínio
    return b"\x05\x01\x00" + addr + struct.pack("!H", port)


async def open_via_socks5(proxy_host: str, proxy_port: int, dest_host: str,
                          dest_port: int, timeout: float = 5.0) -> Tuple[
                              asyncio.StreamReader, asyncio.StreamWriter]:
    """Abre uma conexão até (dest_host, dest_port) ATRAVÉS do SOCKS5 em
    (proxy_host, proxy_port). Devolve (reader, writer) do túnel, como o
    asyncio.open_connection normal — o relay usa igual."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(proxy_host, proxy_port), timeout)
    try:
        writer.write(b"\x05\x01\x00")  # versão 5, 1 método, no-auth
        await writer.drain()
        greeting = await asyncio.wait_for(reader.readexactly(2), timeout)
        if greeting != b"\x05\x00":
            raise OSError("SOCKS5: proxy não aceitou no-auth")

        writer.write(build_connect_request(dest_host, dest_port))
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(4), timeout)
        if head[1] != 0x00:
            raise OSError(f"SOCKS5: CONNECT recusado (rep={head[1]})")
        # consome o endereço de bind da resposta — com timeout em CADA read, senão
        # um proxy que manda o header e trava pendura o jogo sem cair no fallback.
        atyp = head[3]
        if atyp == 0x01:
            await asyncio.wait_for(reader.readexactly(4 + 2), timeout)
        elif atyp == 0x03:
            ln = (await asyncio.wait_for(reader.readexactly(1), timeout))[0]
            await asyncio.wait_for(reader.readexactly(ln + 2), timeout)
        elif atyp == 0x04:
            await asyncio.wait_for(reader.readexactly(16 + 2), timeout)
        else:
            raise OSError(f"SOCKS5: ATYP desconhecido ({atyp:#x})")  # cai no fallback
        return reader, writer
    except Exception:
        writer.close()
        raise
