"""Single upstream stream fetcher with one-to-many byte broadcast.

The hub opens one connection to the upstream audio URL and puts each
received chunk on the queue of every current subscriber. Used so the
Pi fetches the radio station once and feeds it to both the HTTP
proxy (WiiM's audio) and the decoder (visualizer FFT) without
doubling WAN bandwidth.

Subscribers are bounded queues — if a consumer falls behind, its
queue fills and new bytes for that subscriber are dropped. Other
subscribers keep flowing. This is the right behavior for a live
stream: there's no back-pressure we can apply upstream, so a slow
consumer loses data rather than blocking everyone.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

UPSTREAM_CHUNK = 8_192                 # bytes per upstream read
SUBSCRIBER_QUEUE_MAX = 256             # ~2 MB buffer per subscriber
RECONNECT_DELAY_S = 2.0
REQUEST_TIMEOUT_S = 10.0


class StreamHub:
    def __init__(self, url: str) -> None:
        self.url = url
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._content_type = "audio/mpeg"

    @property
    def content_type(self) -> str:
        return self._content_type

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._fetch_loop, name="stream-hub", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=SUBSCRIBER_QUEUE_MAX)
        with self._lock:
            self._subs.append(q)
        log.debug("subscriber added (total=%d)", len(self._subs))
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)
        log.debug("subscriber removed (total=%d)", len(self._subs))

    def _broadcast(self, chunk: bytes) -> None:
        with self._lock:
            subs = list(self._subs)
        dropped = 0
        for q in subs:
            try:
                q.put_nowait(chunk)
            except queue.Full:
                dropped += 1
        if dropped:
            log.debug("dropped chunk for %d slow subscribers", dropped)

    def _fetch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._fetch_once()
            except Exception as e:
                log.warning("upstream fetch error: %s", e)
            if not self._stop.is_set():
                log.info("reconnecting to upstream in %.1fs", RECONNECT_DELAY_S)
                time.sleep(RECONNECT_DELAY_S)

    def _fetch_once(self) -> None:
        log.info("upstream fetch: %s", self.url)
        with requests.get(
            self.url,
            stream=True,
            timeout=REQUEST_TIMEOUT_S,
            allow_redirects=True,
            headers={"User-Agent": "RadioWall/0.1", "Icy-MetaData": "0"},
        ) as r:
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "").split(";")[0].strip()
            if ct:
                self._content_type = ct
            log.info("upstream connected: %s %s", r.status_code, self._content_type)

            for chunk in r.iter_content(chunk_size=UPSTREAM_CHUNK):
                if self._stop.is_set():
                    return
                if chunk:
                    self._broadcast(chunk)
