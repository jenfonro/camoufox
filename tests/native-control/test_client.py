"""Transport tests independent of a browser binary."""
import concurrent.futures
import json
from pathlib import Path
import socket
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from native_control_client import ControlClient, ControlError


class Server:
    def __init__(self, handler):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.endpoint = {"protocolVersion": 1, "transport": "loopback-tcp-ndjson",
                         "instance": "test-instance", "host": "127.0.0.1",
                         "port": self.listener.getsockname()[1]}
        self.errors = []
        self.thread = threading.Thread(target=self.run, args=(handler,), daemon=True)
        self.thread.start()

    def run(self, handler):
        try:
            connection, _ = self.listener.accept()
            with connection, connection.makefile("rb") as reader:
                handler(connection, reader)
        except BaseException as error:
            self.errors.append(error)
        finally:
            self.listener.close()

    def close(self):
        self.thread.join(5)
        assert not self.thread.is_alive()
        assert not self.errors, self.errors


def read(reader):
    return json.loads(reader.readline())


def send(connection, message):
    connection.sendall((json.dumps(message, ensure_ascii=False) + "\n").encode())


def handshake(connection, reader):
    request = read(reader)
    assert request["method"] == "control.connect" and request["params"]["token"] == "test-token"
    send(connection, {"id": request["id"], "result": {
        "instance": "test-instance", "protocolVersion": 1, "session": "test",
        "capabilities": {}}})


class ClientTests(unittest.TestCase):
    def test_out_of_order_and_unicode_event(self):
        def handler(connection, reader):
            handshake(connection, reader)
            first, second = read(reader), read(reader)
            send(connection, {"id": second["id"], "result": {"value": 2}})
            data = (json.dumps({"method": "page.test", "params": {"text": "你好"}}, ensure_ascii=False) + "\n").encode()
            # Exercise UTF-8 and JSON split across arbitrary TCP reads.
            for byte in data:
                connection.sendall(bytes([byte]))
            send(connection, {"id": first["id"], "result": {"value": 1}})
            reader.read()

        server = Server(handler)
        try:
            with ControlClient(server.endpoint, "test-token") as client:
                _, first = client.request("first")
                _, second = client.request("second")
                self.assertEqual(second.result(3), {"value": 2})
                self.assertEqual(first.result(3), {"value": 1})
                self.assertEqual(client.events.get(timeout=3)["params"]["text"], "你好")
        finally:
            server.close()

    def test_authentication_error(self):
        def handler(connection, reader):
            request = read(reader)
            send(connection, {"id": request["id"], "error": {
                "code": "authentication failed", "message": "Connection authorization failed"}})

        server = Server(handler)
        try:
            with self.assertRaises(ControlError) as caught:
                ControlClient(server.endpoint, "wrong-token")
            self.assertEqual(caught.exception.code, "authentication failed")
        finally:
            server.close()

    def test_disconnect_rejects_pending_request(self):
        def handler(connection, reader):
            handshake(connection, reader)
            read(reader)

        server = Server(handler)
        try:
            with ControlClient(server.endpoint, "test-token") as client:
                _, pending = client.request("pending")
                with self.assertRaises(ConnectionError):
                    pending.result(3)
        finally:
            server.close()

    def test_rejects_nonlocal_endpoint(self):
        with self.assertRaises(ValueError):
            ControlClient({"protocolVersion": 1, "transport": "loopback-tcp-ndjson",
                           "host": "example.com", "port": 1}, "token")

    def test_invalid_json_and_local_cancel_keep_connection_usable(self):
        def handler(connection, reader):
            handshake(connection, reader)
            first, second = read(reader), read(reader)
            send(connection, {"id": first["id"], "result": {}})
            send(connection, {"id": second["id"], "result": {"alive": True}})
            reader.read()

        server = Server(handler)
        try:
            with ControlClient(server.endpoint, "test-token") as client:
                with self.assertRaises(ValueError):
                    client.request("bad", {"value": float("nan")})
                self.assertFalse(client._pending)
                _, pending = client.request("cancelled-locally")
                pending.cancel()
                self.assertEqual(client.call("next"), {"alive": True})
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
