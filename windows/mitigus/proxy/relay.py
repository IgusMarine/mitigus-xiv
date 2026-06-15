"""
Relay TCP transparente (o coração da Fase 1).

Para cada conexão que o WinDivert desvia para cá, o relay:
  1. descobre o peer (o PS5) e resolve o destino ORIGINAL (servidor) via conntrack
  2. abre uma conexão NOVA upstream para o servidor real (com o IP do PRÓPRIO PC,
     então as respostas voltam naturalmente para o PC — resolve o caminho de volta
     da topologia de NIC única)
  3. bombeia bytes nos dois sentidos, passando cada pedaço por um hook de transform

Como cada lado é uma conexão TCP REAL terminada pelo SO, mudar o tamanho do
payload (Fase 4, ao reescrever o animation_lock) é seguro: não há seq/ack para
ressincronizar manualmente. Os hooks `on_c2s`/`on_s2c` são onde a mitigação entra
depois; na Fase 1 eles são identidade (passthrough).

Este módulo NÃO depende do WinDivert — é testável em loopback.
"""
from __future__ import annotations

import asyncio
import socket
from typing import Callable, Optional, Tuple


def _nodelay(writer: "asyncio.StreamWriter") -> None:
    """Desliga o Nagle no socket (envia a ação na hora, sem juntar pacotes).

    O asyncio já liga TCP_NODELAY por padrão, mas reforçamos explicitamente nos
    dois hops que o relay controla — é o 'Reduce Packet Delay' do XivAlexander,
    e aqui temos os dois lados (PS5->PC e PC->servidor)."""
    sock = writer.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass


def _keepalive(writer: "asyncio.StreamWriter") -> None:
    """Liga TCP keepalive no upstream pra detectar link morto (BR->NA caindo)
    rápido, em vez de o socket ficar pendurado até um boot 90k silencioso."""
    sock = writer.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass

Peer = Tuple[str, int]
Resolver = Callable[[Peer], Optional[Peer]]
Transform = Callable[[bytes], bytes]


def _identity(data: bytes) -> bytes:
    return data


class TransparentRelay:
    def __init__(
        self,
        resolve: Resolver,
        listen_host: str = "0.0.0.0",
        listen_port: int = 0,
        on_c2s: Optional[Transform] = None,
        on_s2c: Optional[Transform] = None,
        processor_factory: Optional[Callable[[Peer, Peer], object]] = None,
        connect_timeout: float = 5.0,
        connect_upstream: Optional[Callable] = None,
    ) -> None:
        self._resolve = resolve
        self._listen_host = listen_host
        self._listen_port = listen_port
        self._on_c2s = on_c2s or _identity
        self._on_s2c = on_s2c or _identity
        # como abrir a conexão de subida (PC->servidor). Default: direta. A rota
        # opcional (SOCKS5/VPS) injeta outro conector aqui. Assinatura:
        #   async (host, port, timeout) -> (reader, writer)
        self._connect_upstream = connect_upstream
        # fábrica por conexão: recebe (peer, dest) e devolve um objeto com
        # .c2s(bytes)->bytes e .s2c(bytes)->bytes, ou None para passthrough.
        self._processor_factory = processor_factory
        self._connect_timeout = connect_timeout
        self._server: Optional[asyncio.AbstractServer] = None
        self.port: Optional[int] = None
        self._upstreams: dict = {}  # conexões de subida vivas (p/ ler o ping WAN)

    async def start(self) -> int:
        self._server = await asyncio.start_server(
            self._handle, self._listen_host, self._listen_port
        )
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def serve_forever(self) -> None:
        assert self._server is not None, "chame start() antes de serve_forever()"
        async with self._server:
            await self._server.serve_forever()

    async def _handle(self, c_reader: asyncio.StreamReader, c_writer: asyncio.StreamWriter) -> None:
        peer = c_writer.get_extra_info("peername")
        dest = self._resolve(peer) if peer else None
        if dest is None:
            c_writer.close()
            return
        try:
            if self._connect_upstream is not None:
                s_reader, s_writer = await self._connect_upstream(
                    dest[0], dest[1], self._connect_timeout)
            else:
                s_reader, s_writer = await asyncio.wait_for(
                    asyncio.open_connection(dest[0], dest[1]), self._connect_timeout)
        except (OSError, asyncio.TimeoutError):
            c_writer.close()
            return

        _nodelay(c_writer)  # PS5 -> PC
        _nodelay(s_writer)  # PC -> servidor
        _keepalive(s_writer)

        up_key = id(s_writer)
        up_sock = s_writer.get_extra_info("socket")
        if up_sock is not None:
            self._upstreams[up_key] = up_sock

        on_c2s, on_s2c = self._on_c2s, self._on_s2c
        if self._processor_factory is not None:
            proc = self._processor_factory(peer, dest)
            if proc is not None:
                on_c2s, on_s2c = proc.c2s, proc.s2c

        try:
            t1 = asyncio.create_task(self._pump(c_reader, s_writer, on_c2s))
            t2 = asyncio.create_task(self._pump(s_reader, c_writer, on_s2c))
            _, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
            for w in (c_writer, s_writer):
                if not w.is_closing():
                    w.close()
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            self._upstreams.pop(up_key, None)

    def active_count(self) -> int:
        """Quantas conexões de jogo (upstream) estão vivas agora."""
        return len(self._upstreams)

    def sample_upstream_tcp_info(self) -> Optional[dict]:
        """Ping da perna PC->servidor: lê o TCP_INFO de uma conexão de subida viva.

        Todas as conexões do FFXIV vão pro mesmo data center, então qualquer uma
        viva dá o RTT da rede. Devolve None se não houver conexão ou no não-Windows."""
        from ..net.tcpinfo import query_tcp_info

        for sock in list(self._upstreams.values()):
            info = query_tcp_info(sock)
            if info is not None:
                return info
        return None

    async def _pump(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, transform: Transform
    ) -> None:
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                out = transform(data)
                if out:
                    writer.write(out)
                    await writer.drain()
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            if not writer.is_closing():
                writer.close()
