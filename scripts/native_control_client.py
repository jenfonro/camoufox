#!/usr/bin/env python3
"""Small standard-library client for Camoufox native control protocol v1.

The caller supplies the token out of band; the endpoint file never contains it.
No Playwright, WebDriver, extension, or debugger dependency is used.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import queue
import socket
import threading
from typing import Any


class ControlError(RuntimeError):
    def __init__(self, error: dict[str, Any]):
        self.code = error.get("code", "unknown error")
        super().__init__(f"{self.code}: {error.get('message', '')}")


class ControlClient:
    """One authorized connection. Commands can run concurrently; input is queued."""

    def __init__(self, endpoint: str | Path | dict, token: str, timeout: float = 10):
        if not isinstance(endpoint, dict):
            endpoint = json.loads(Path(endpoint).read_text(encoding="utf-8"))
        if endpoint.get("protocolVersion") != 1 or endpoint.get("transport") != "loopback-tcp-ndjson":
            raise ValueError("Unsupported endpoint protocol")
        if endpoint.get("host") not in ("127.0.0.1", "::1"):
            raise ValueError("Only a loopback endpoint is supported")
        self.socket = socket.create_connection((endpoint["host"], endpoint["port"]), timeout)
        self.socket.settimeout(None)
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, concurrent.futures.Future] = {}
        self._next_id = 0
        self._closed = False
        self.events: queue.Queue[dict] = queue.Queue(maxsize=10000)
        self._reader = threading.Thread(target=self._read, name="camoufox-control-reader", daemon=True)
        self._reader.start()
        try:
            self.connection = self.call("control.connect", {"protocolVersion": 1, "token": token}, timeout=timeout)
            if self.connection["instance"] != endpoint["instance"]:
                raise RuntimeError("Endpoint now belongs to a different browser instance")
        except BaseException:
            self.close()
            raise

    def request(self, method: str, params: dict | None = None, *, timeout: float = 30):
        """Return (request id, Future); use control.cancel with that id to cancel."""
        future: concurrent.futures.Future = concurrent.futures.Future()
        with self._pending_lock:
            if self._closed:
                raise ConnectionError("Control connection is closed")
            self._next_id += 1
            request_id = self._next_id
            self._pending[request_id] = future
        message = {"id": request_id, "method": method, "params": params or {},
                   "timeout": max(1, min(120000, round(timeout * 1000)))}
        try:
            data = (json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("Request exceeds the protocol frame limit")
        except BaseException:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise
        try:
            with self._write_lock:
                self.socket.sendall(data)
        except BaseException:
            self.close()
            raise
        return request_id, future

    def call(self, method: str, params: dict | None = None, *, timeout: float = 30):
        request_id, future = self.request(method, params, timeout=timeout)
        try:
            return future.result(timeout=timeout + 2)
        except concurrent.futures.TimeoutError:
            try:
                self.request("control.cancel", {"request": request_id}, timeout=2)
            except (OSError, ConnectionError):
                pass
            raise

    def subscribe(self, *events: str, contexts: list[str] | None = None):
        params: dict[str, Any] = {"events": list(events)}
        if contexts is not None:
            params["contexts"] = contexts
        return self.call("control.subscribe", params)["subscription"]

    def _read(self):
        error: BaseException = ConnectionError("Browser closed the control connection")
        try:
            with self.socket.makefile("rb") as stream:
                while not self._closed:
                    line = stream.readline(64 * 1024 * 1024 + 1)
                    if not line:
                        break
                    if not line.endswith(b"\n") or len(line) > 64 * 1024 * 1024:
                        raise ValueError("Response exceeds the protocol frame limit")
                    message = json.loads(line)
                    if "id" in message:
                        with self._pending_lock:
                            future = self._pending.pop(message["id"], None)
                        if future is None or future.done():
                            continue
                        if "error" in message:
                            future.set_exception(ControlError(message["error"]))
                        else:
                            future.set_result(message["result"])
                    else:
                        # Do not silently discard events, notably intercepted
                        # requests. A stalled consumer closes and releases its
                        # interceptions at the browser.
                        self.events.put_nowait(message)
        except BaseException as exc:
            error = exc
        finally:
            self._disconnect(error)

    def _disconnect(self, error: BaseException):
        with self._pending_lock:
            self._closed = True
            pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(error)
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()

    def close(self):
        self._disconnect(ConnectionError("Control client disconnected"))
        if threading.current_thread() is not self._reader:
            self._reader.join(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", type=Path, required=True)
    parser.add_argument("--token-env", default="CAMOUFOX_CONTROL_TOKEN")
    parser.add_argument("method", nargs="?", default="browser.getInfo")
    parser.add_argument("params", nargs="?", default="{}")
    args = parser.parse_args()
    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"Set {args.token_env} to the launch token")
    with ControlClient(args.endpoint, token) as client:
        print(json.dumps(client.call(args.method, json.loads(args.params)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
