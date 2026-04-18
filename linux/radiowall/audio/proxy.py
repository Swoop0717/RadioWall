"""HTTP proxy exposing the hub's live stream at /stream.mp3.

Tells WiiM (or any media renderer) to play from the Pi instead of
Radio.garden directly:

    curl -k "https://<wiim>/httpapi.asp?command=\
             setPlayerCmd:play:http://<pi>:8000/stream.mp3"

Each connection subscribes to the hub on GET, writes bytes as they
arrive, and unsubscribes on disconnect. ThreadingHTTPServer so
multiple clients each get their own thread (not strictly needed for
a single WiiM, but free).
"""

from __future__ import annotations

import http.server
import logging
import queue
import threading
from socketserver import ThreadingMixIn
from typing import Optional

from radiowall.audio.hub import StreamHub

log = logging.getLogger(__name__)

STREAM_PATH = "/stream.mp3"
CLIENT_IDLE_TIMEOUT_S = 30


class _ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(http.server.BaseHTTPRequestHandler):
    # set on the server instance below
    server: "_ThreadingHTTPServer"

    def log_message(self, fmt: str, *args) -> None:
        log.debug("http: " + fmt, *args)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        hub: StreamHub = getattr(self.server, "hub")
        if self.path != STREAM_PATH:
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", hub.content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        client = self.client_address[0]
        log.info("client connected: %s", client)
        q = hub.subscribe()
        try:
            while True:
                try:
                    chunk = q.get(timeout=CLIENT_IDLE_TIMEOUT_S)
                except queue.Empty:
                    log.info("client idle-timeout: %s", client)
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    log.info("client disconnected: %s", client)
                    break
        finally:
            hub.unsubscribe(q)


_server: Optional[_ThreadingHTTPServer] = None


def start(hub: StreamHub, port: int = 8000, bind: str = "0.0.0.0") -> None:
    global _server
    stop()
    _server = _ThreadingHTTPServer((bind, port), _Handler)
    _server.hub = hub  # type: ignore[attr-defined]
    threading.Thread(
        target=_server.serve_forever, name="stream-proxy", daemon=True
    ).start()
    log.info("stream proxy listening on http://%s:%d%s", bind, port, STREAM_PATH)


def stop() -> None:
    global _server
    if _server is not None:
        _server.shutdown()
        _server = None
