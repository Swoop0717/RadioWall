"""Subscribe to a StreamHub, decode via ffmpeg, expose FFT bands.

Hub → ffmpeg stdin (writer thread) → ffmpeg stdout (reader thread) →
FFT on fixed-size windows → smoothed band levels → `get_bands()`.

ffmpeg handles whatever codec the radio sends (MP3, AAC, etc.) and
resamples to 16-bit mono PCM at 44.1 kHz for a predictable FFT.

Visualizer calls `get_bands()` every frame; missing/not-running
capture returns None and visualizer falls back to its sine animation.
"""

from __future__ import annotations

import logging
import queue
import shutil
import subprocess
import threading
from typing import Optional

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

from radiowall.audio.hub import StreamHub

log = logging.getLogger(__name__)

SAMPLE_RATE = 44_100
CHUNK_SAMPLES = 2048              # ~46 ms at 44.1 kHz
NUM_BANDS = 8
BAND_LO_HZ = 60.0
BAND_HI_HZ = 8_000.0
SMOOTH_ALPHA = 0.35
NORMALIZE_GAIN = 1.6


class _Decoder:
    def __init__(self, hub: StreamHub) -> None:
        self._hub = hub
        self._sub: Optional[queue.Queue] = None
        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._smooth = [0.0] * NUM_BANDS
        self._lock = threading.Lock()
        self._writer_thread: Optional[threading.Thread] = None
        self._reader_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if np is None:
            log.warning("numpy unavailable; decoder disabled")
            return
        if not shutil.which("ffmpeg"):
            log.warning("ffmpeg not installed; decoder disabled "
                        "(apt install ffmpeg)")
            return

        self._stop.clear()
        self._sub = self._hub.subscribe()
        # content-type-based format hint avoids probe delay and silent
        # failures when the stream header is split across chunks
        ctype = self._hub.content_type.lower()
        fmt_hint: list[str] = []
        if "mpeg" in ctype or "mp3" in ctype:
            fmt_hint = ["-f", "mp3"]
        elif "aac" in ctype:
            fmt_hint = ["-f", "aac"]
        elif "ogg" in ctype:
            fmt_hint = ["-f", "ogg"]

        self._proc = subprocess.Popen(
            [
                "ffmpeg", "-loglevel", "warning", "-nostdin",
                *fmt_hint,
                "-i", "pipe:0",
                "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE),
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._writer_thread = threading.Thread(
            target=self._writer, name="decoder-writer", daemon=True)
        self._reader_thread = threading.Thread(
            target=self._reader, name="decoder-reader", daemon=True)
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, name="decoder-stderr", daemon=True)
        self._writer_thread.start()
        self._reader_thread.start()
        self._stderr_thread.start()
        log.info("decoder started (format hint: %s)",
                 " ".join(fmt_hint) if fmt_hint else "autodetect")

    def stop(self) -> None:
        self._stop.set()
        if self._sub is not None:
            self._hub.unsubscribe(self._sub)
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass

    def get_bands(self) -> list[float]:
        with self._lock:
            return list(self._smooth)

    def _drain_stderr(self) -> None:
        """Log ffmpeg stderr line-by-line; otherwise its pipe buffer
        fills at ~64 KB and ffmpeg blocks (which looks like an early
        exit from our side)."""
        assert self._proc is not None and self._proc.stderr is not None
        for raw in iter(self._proc.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                log.info("ffmpeg: %s", line)

    def _writer(self) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        try:
            while not self._stop.is_set():
                try:
                    chunk = self._sub.get(timeout=1)  # type: ignore[union-attr]
                except queue.Empty:
                    continue
                try:
                    self._proc.stdin.write(chunk)
                except BrokenPipeError:
                    return
        finally:
            try:
                self._proc.stdin.close()
            except Exception:
                pass

    def _reader(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        window = np.hanning(CHUNK_SAMPLES).astype(np.float32)
        freqs = np.fft.rfftfreq(CHUNK_SAMPLES, 1.0 / SAMPLE_RATE)
        edges = np.logspace(
            np.log10(BAND_LO_HZ), np.log10(BAND_HI_HZ), NUM_BANDS + 1)
        masks = [
            (freqs >= lo) & (freqs < hi)
            for lo, hi in zip(edges[:-1], edges[1:])
        ]

        bytes_per_chunk = CHUNK_SAMPLES * 2
        while not self._stop.is_set():
            raw = self._proc.stdout.read(bytes_per_chunk)
            if len(raw) < bytes_per_chunk:
                log.info("decoder pcm stream ended")
                return

            samples = (
                np.frombuffer(raw, dtype=np.int16)
                  .astype(np.float32) / 32768.0
            )
            spec = np.abs(np.fft.rfft(samples * window))
            raw_levels = [
                float(np.mean(spec[m])) if m.any() else 0.0 for m in masks
            ]
            peak = max(raw_levels) or 1.0
            norm = [min(1.0, v / peak * NORMALIZE_GAIN) for v in raw_levels]
            with self._lock:
                for i, v in enumerate(norm):
                    self._smooth[i] = (
                        (1 - SMOOTH_ALPHA) * self._smooth[i] + SMOOTH_ALPHA * v
                    )


_singleton: Optional[_Decoder] = None


def start(hub: StreamHub) -> None:
    global _singleton
    stop()
    _singleton = _Decoder(hub)
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
