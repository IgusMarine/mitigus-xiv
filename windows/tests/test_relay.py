import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.proxy.relay import TransparentRelay


async def _echo(reader, writer):
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


class RelayTest(unittest.IsolatedAsyncioTestCase):
    async def test_bidirectional_with_transform(self):
        up = await asyncio.start_server(_echo, "127.0.0.1", 0)
        up_addr = up.sockets[0].getsockname()
        relay = TransparentRelay(
            resolve=lambda peer: (up_addr[0], up_addr[1]),
            listen_host="127.0.0.1",
            listen_port=0,
            on_s2c=lambda b: b.upper(),
        )
        port = await relay.start()
        serve = asyncio.create_task(relay.serve_forever())
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"hello world")
            await writer.drain()
            data = await asyncio.wait_for(reader.readexactly(11), timeout=2.0)
            self.assertEqual(data, b"HELLO WORLD")  # eco passou pelo transform
            writer.close()
        finally:
            serve.cancel()
            up.close()
            await asyncio.gather(serve, return_exceptions=True)

    async def test_unresolved_peer_is_dropped(self):
        relay = TransparentRelay(
            resolve=lambda peer: None,
            listen_host="127.0.0.1",
            listen_port=0,
        )
        port = await relay.start()
        serve = asyncio.create_task(relay.serve_forever())
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            data = await asyncio.wait_for(reader.read(), timeout=2.0)
            self.assertEqual(data, b"")  # destino não resolvido => conexão fechada
            writer.close()
        finally:
            serve.cancel()
            await asyncio.gather(serve, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
