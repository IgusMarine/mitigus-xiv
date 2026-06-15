import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus.net.tcpinfo import query_tcp_info


class TcpInfoTest(unittest.TestCase):
    def test_loopback_connection_returns_info(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        cli = socket.create_connection(("127.0.0.1", port), timeout=5)
        conn, _ = srv.accept()
        try:
            cli.sendall(b"hello")
            conn.recv(5)
            info = query_tcp_info(cli)
            # Em Windows deve devolver dict; valida que a struct ctypes foi lida certo.
            self.assertIsNotNone(info, "query_tcp_info devolveu None num socket conectado")
            for k in ("rtt_ms", "min_rtt_ms", "bytes_out", "bytes_retrans", "timeout_episodes"):
                self.assertIn(k, info)
            self.assertGreaterEqual(info["rtt_ms"], 0.0)
            self.assertLess(info["rtt_ms"], 60000.0)        # sanidade (< 60s)
            self.assertGreaterEqual(info["bytes_out"], 0)
        finally:
            cli.close()
            conn.close()
            srv.close()

    def test_bad_socket_returns_none(self):
        class _Bad:
            def fileno(self):
                return -1
        self.assertIsNone(query_tcp_info(_Bad()))


if __name__ == "__main__":
    unittest.main()
