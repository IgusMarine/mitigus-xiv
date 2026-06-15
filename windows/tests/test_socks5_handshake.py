import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.net.socks5 import open_via_socks5


async def _start(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    return server, host, port


async def _read_connect(r):
    await r.readexactly(3)               # greeting (ver, nmethods, no-auth)
    head = await r.readexactly(4)        # ver, cmd, rsv, atyp
    atyp = head[3]
    if atyp == 1:
        await r.readexactly(4 + 2)
    elif atyp == 3:
        ln = (await r.readexactly(1))[0]
        await r.readexactly(ln + 2)


class Socks5HandshakeTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_tunnel(self):
        async def handler(r, w):
            w.write(b"\x05\x00"); await w.drain()        # aceita no-auth
            await _read_connect(r)
            w.write(b"\x05\x00\x00\x01" + b"\x00" * 6); await w.drain()  # sucesso
            data = await r.readexactly(2)
            w.write(b"OK:" + data); await w.drain()
            w.close()

        server, host, port = await _start(handler)
        async with server:
            r, w = await open_via_socks5(host, port, "8.8.8.8", 443, timeout=2)
            w.write(b"hi"); await w.drain()
            self.assertEqual(await asyncio.wait_for(r.readexactly(5), 2), b"OK:hi")
            w.close()

    async def test_unknown_atyp_raises(self):
        async def handler(r, w):
            w.write(b"\x05\x00"); await w.drain()
            await _read_connect(r)
            w.write(b"\x05\x00\x00\x02\x00\x00"); await w.drain()  # ATYP inválido (0x02)
            await asyncio.sleep(0.2); w.close()

        server, host, port = await _start(handler)
        async with server:
            with self.assertRaises(OSError):
                await open_via_socks5(host, port, "8.8.8.8", 443, timeout=2)

    async def test_stall_times_out(self):
        # proxy manda o header da resposta e TRAVA antes do endereço.
        # Sem o wait_for em cada read, isto penduraria pra sempre.
        async def handler(r, w):
            w.write(b"\x05\x00"); await w.drain()
            await _read_connect(r)
            w.write(b"\x05\x00\x00\x01"); await w.drain()   # só o header; sem os 6 bytes
            await asyncio.sleep(5)
            w.close()

        server, host, port = await _start(handler)
        async with server:
            with self.assertRaises((asyncio.TimeoutError, OSError)):
                await open_via_socks5(host, port, "8.8.8.8", 443, timeout=0.3)

    async def test_proxy_rejects_noauth(self):
        async def handler(r, w):
            await r.readexactly(3)
            w.write(b"\x05\xff"); await w.drain()   # nenhum método aceito
            w.close()

        server, host, port = await _start(handler)
        async with server:
            with self.assertRaises(OSError):
                await open_via_socks5(host, port, "8.8.8.8", 443, timeout=2)


if __name__ == "__main__":
    unittest.main()
