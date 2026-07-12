"""Decode the radio stream and expose FFT-banded levels.

Runs `ffmpeg -i <url> -f s16le -ac 1 -ar 44100 -` on its own
connection to the stream and FFTs the PCM output. We used to pipe
bytes from the StreamHub into ffmpeg's stdin to avoid a second
WAN connection, but that turned out to be hard to keep alive —
ffmpeg wants a stable input and early stdin-pipe EOFs silently
killed the process. The extra ~16 KB/s of upstream traffic for a
second fetch is irrelevant here.

`get_bands()` returns the latest smoothed levels (0..1 per band)
or None if the decoder isn't running (missing ffmpeg, missing
numpy, no URL configured).
"""

from __future__ import annotations

import collections
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Optional

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

log = logging.getLogger(__name__)

SAMPLE_RATE = 44_100
CHUNK_SAMPLES = 1024              # ~23 ms → ~43 band updates/s
NUM_BANDS = 8
BAND_LO_HZ = 60.0
BAND_HI_HZ = 8_000.0
SMOOTH_ALPHA = 0.25
NORMALIZE_GAIN = 1.6

# The WiiM buffers seconds of stream before you HEAR it, while our own
# ffmpeg tap reacts almost live — so the raw visualizer dances ahead of
# the music. Band frames are kept in a timestamped ring; get_bands()
# returns the frame from RADIOWALL_VIS_DELAY seconds ago. Tune by ear.
VIS_DELAY_S = float(os.getenv("RADIOWALL_VIS_DELAY", "0") or 0)
_HISTORY_S = max(12.0, VIS_DELAY_S + 2.0)
_HISTORY_LEN = int(_HISTORY_S * SAMPLE_RATE / CHUNK_SAMPLES)


class _Decoder:
    def __init__(self, url: str) -> None:
        self._url = url
        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._smooth = [0.0] * NUM_BANDS
        self._history: collections.deque[tuple[float, list[float]]] = \
            collections.deque(maxlen=_HISTORY_LEN)
        self._lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if np is None:
            log.warning("numpy unavailable; decoder disabled")
            return
        if not shutil.which("ffmpeg"):
            log.warning("ffmpeg not installed; decoder disabled "
                        "(apt install ffmpeg)")
            return

        self._stop.clear()
        self._reader_thread = threading.Thread(
            target=self._supervise, name="decoder", daemon=True)
        self._reader_thread.start()
        log.info("decoder started on %s", self._url)

    def _spawn(self) -> None:
        self._proc = subprocess.Popen(
            [
                "ffmpeg", "-loglevel", "warning", "-nostdin",
                # Some stations 404/close ffmpeg's default UA while serving
                # real players fine (the WiiM plays where our tap dies).
                "-user_agent", "VLC/3.0.20 LibVLC/3.0.20",
                "-reconnect", "1", "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-i", self._url,
                "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE),
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, name="decoder-stderr", daemon=True)
        self._stderr_thread.start()

    def _supervise(self) -> None:
        """Keep an ffmpeg alive for as long as the decoder is wanted.

        ffmpeg's -reconnect only covers hiccups inside a living process;
        streams that 404, close immediately, or make ffmpeg exit would
        otherwise leave the visualizer flat until the next station change
        (seen live: 'pcm stream ended, got 0/4096 bytes')."""
        backoff = 2.0
        while not self._stop.is_set():
            self._spawn()
            started = self._read_pcm()          # blocks until EOF/stop
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            if self._stop.is_set():
                return
            with self._lock:
                # Reset the live-path levels, but KEEP the delayed history:
                # across a same-station reconnect the delayed visualizer
                # briefly freezes on the last real frame instead of going
                # dark for backoff + VIS_DELAY seconds.
                self._smooth = [0.0] * NUM_BANDS
            backoff = 2.0 if started else min(backoff * 2, 15.0)
            log.info("decoder retrying in %.0fs", backoff)
            if self._stop.wait(backoff):
                return

    def stop(self) -> None:
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass

    def get_bands(self) -> list[float]:
        with self._lock:
            if VIS_DELAY_S <= 0:
                return list(self._smooth)
            cutoff = time.monotonic() - VIS_DELAY_S
            # newest frame that is at least VIS_DELAY_S old
            for ts, bands in reversed(self._history):
                if ts <= cutoff:
                    return list(bands)
            # not enough history yet (just tuned in): stay quiet until the
            # delayed timeline catches up — matches what you're hearing
            return [0.0] * NUM_BANDS

    def _drain_stderr(self) -> None:
        """Read stderr line-by-line and log it; prevents the 64 KB
        kernel pipe buffer from filling up and blocking ffmpeg."""
        assert self._proc is not None and self._proc.stderr is not None
        for raw in iter(self._proc.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                log.info("ffmpeg: %s", line)

    def _read_pcm(self) -> bool:
        """Read PCM until EOF/stop; returns True if any audio was decoded
        (used by the supervisor to pick the retry backoff)."""
        assert self._proc is not None and self._proc.stdout is not None
        decoded_any = False
        # Stream-time pacing: HTTP radio arrives in ~1 s bursts, so chunk
        # ARRIVAL times cluster and the delayed visualizer would replay
        # those clusters ("updates once a second"). Each chunk is exactly
        # CHUNK_SAMPLES/rate seconds of audio — timestamp it on that grid,
        # anchored to the wall clock, re-anchoring only on a real stall.
        chunk_s = CHUNK_SAMPLES / SAMPLE_RATE
        anchor: float | None = None
        chunk_idx = 0
        window = np.hanning(CHUNK_SAMPLES).astype(np.float32)
        freqs = np.fft.rfftfreq(CHUNK_SAMPLES, 1.0 / SAMPLE_RATE)
        edges = np.logspace(
            np.log10(BAND_LO_HZ), np.log10(BAND_HI_HZ), NUM_BANDS + 1)
        masks = [
            (freqs >= lo) & (freqs < hi)
            for lo, hi in zip(edges[:-1], edges[1:])
        ]

        bytes_per_chunk = CHUNK_SAMPLES * 2
        stdout = self._proc.stdout
        buf = bytearray(bytes_per_chunk)
        view = memoryview(buf)
        while not self._stop.is_set():
            # read EXACTLY bytes_per_chunk; .read() on a subprocess pipe
            # returns "what's currently available", not a fixed length
            got = 0
            while got < bytes_per_chunk:
                n = stdout.readinto(view[got:])
                if not n:
                    rc = self._proc.poll()
                    log.info("decoder pcm stream ended (ffmpeg rc=%s, got %d/%d bytes)",
                             rc, got, bytes_per_chunk)
                    return decoded_any
                got += n
            decoded_any = True

            samples = (
                np.frombuffer(bytes(buf), dtype=np.int16)
                  .astype(np.float32) / 32768.0
            )
            spec = np.abs(np.fft.rfft(samples * window))
            raw_levels = [
                float(np.mean(spec[m])) if m.any() else 0.0 for m in masks
            ]
            peak = max(raw_levels) or 1.0
            norm = [min(1.0, v / peak * NORMALIZE_GAIN) for v in raw_levels]
            now = time.monotonic()
            if anchor is None:
                anchor = now
            ts = anchor + chunk_idx * chunk_s
            if ts < now - 0.5:            # stream stalled → snap forward
                anchor = now - chunk_idx * chunk_s
                ts = now
            chunk_idx += 1

            with self._lock:
                for i, v in enumerate(norm):
                    self._smooth[i] = (
                        (1 - SMOOTH_ALPHA) * self._smooth[i] + SMOOTH_ALPHA * v
                    )
                self._history.append((ts, list(self._smooth)))


_singleton: Optional[_Decoder] = None


def start(url: str) -> None:
    global _singleton
    stop()
    _singleton = _Decoder(url)
    _singleton.start()


def stop() -> None:
    global _singleton
    if _singleton is not None:
        _singleton.stop()
        _singleton = None


def get_bands() -> Optional[list[float]]:
    if _singleton is None:
        return None
    return _singleton.get_bands()
