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
numpy, no URL configured). `get_wave()` / `get_rms()` expose a
downsampled waveform and loudness for the scope/VU visualizers,
on the same consumption clock as the bands.

Band scaling: web radio has wildly tilted spectra — bass carries
10-40 dB more energy than treble, and lossy encoders shave the top
octave entirely on some stations. Normalizing every band against
the frame-wide peak (the old scheme) therefore parked the right
half of the analyzer at zero. Instead each band now tracks its own
recent peak in dB and displays relative to that (per-band AGC):
quiet-but-real treble dances full-range, while a silence gate keeps
genuinely dead bands dark instead of amplifying encoder noise.
"""

from __future__ import annotations

import collections
import logging
import math
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
# 2048-point FFT advanced 1024 samples at a time: band updates still
# arrive at ~43 Hz, but frequency resolution doubles (21.5 Hz/bin) so
# 16 log-spaced bands all contain at least one bin.
FFT_SIZE = 2048
HOP_SAMPLES = 1024
NUM_BANDS = 16
BAND_LO_HZ = 50.0
BAND_HI_HZ = 12_000.0

# Per-band AGC (dB domain). Each band's reference peak decays a few
# dB/s so the display re-sensitizes when the music gets quieter, and
# a band must clear SILENCE_DB (dBFS-ish, full-scale sine ≈ 0 dB) to
# light up at all — that's what keeps encoder-silence dark.
# 26 dB measured live (SomaFM 128k): band medians land at 0.2-0.5 with
# p90 near 0.7-1.0 — lively without pinning. 42 dB parked everything >0.8.
DB_RANGE = float(os.getenv("RADIOWALL_VIS_RANGE_DB", "26"))
DB_DECAY_PER_S = 4.0
SILENCE_DB = float(os.getenv("RADIOWALL_VIS_GATE_DB", "-62"))
_DB_FLOOR = -120.0

# Fast attack / slow release on the displayed level (classic analyzer
# ballistics — punchy on hits, smooth on decay).
ATTACK = 0.55
RELEASE = 0.20

WAVE_POINTS = 64                  # scope waveform points stored per hop

# The WiiM buffers seconds of stream before you HEAR it, while our own
# ffmpeg tap reacts almost live — so the raw visualizer dances ahead of
# the music. Fix: a consumption clock. Radio servers burst many seconds
# of backlog on connect (SHOUTcast: 10-30 s) and ffmpeg decodes it all
# instantly, so band frames are REPLAYED at real-time pace from the
# moment data first flowed, shifted by RADIOWALL_VIS_DELAY — mirroring
# how the speaker itself consumes the very same burst. (A first attempt
# stamped frames with a synthetic stream clock anchored at connect; the
# burst pushed the whole timeline into the future and the delayed lookup
# never found a frame — visualizer permanently dark on bursty stations.)
VIS_DELAY_S = float(os.getenv("RADIOWALL_VIS_DELAY", "0") or 0)
_CHUNK_S = HOP_SAMPLES / SAMPLE_RATE
_HISTORY_S = max(30.0, VIS_DELAY_S + 5.0)      # must exceed burst + delay
_HISTORY_LEN = int(_HISTORY_S / _CHUNK_S)

_DB_DECAY_PER_CHUNK = DB_DECAY_PER_S * _CHUNK_S


class _Frame:
    """One analysis hop: band levels + scope waveform + loudness."""
    __slots__ = ("bands", "wave", "rms")

    def __init__(self, bands: list[float], wave: list[float], rms: float):
        self.bands = bands
        self.wave = wave
        self.rms = rms


class _Decoder:
    def __init__(self, url: str) -> None:
        self._url = url
        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._smooth = [0.0] * NUM_BANDS
        self._band_peak_db = [_DB_FLOOR] * NUM_BANDS
        self._history: collections.deque[_Frame] = \
            collections.deque(maxlen=_HISTORY_LEN)
        self._t0: Optional[float] = None      # wall time of first band frame
        self._frames_total = 0                # appended ever (incl. evicted)
        self._lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._dsp = None                      # lazily-built numpy arrays

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
                self._band_peak_db = [_DB_FLOOR] * NUM_BANDS
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

    # -------- consumption-clock reads ---------------------------------

    def _index(self) -> Optional[int]:
        """History index that should be 'audible' now (lock held)."""
        if not self._history:
            return None
        if VIS_DELAY_S <= 0:
            return len(self._history) - 1
        if self._t0 is None:
            return None
        idx = int((time.monotonic() - self._t0 - VIS_DELAY_S) / _CHUNK_S)
        if idx < 0:
            return None                        # still inside delay warm-up
        evicted = self._frames_total - len(self._history)
        i = idx - evicted
        if i < 0:
            return 0                           # fell behind eviction → oldest
        if i >= len(self._history):
            return len(self._history) - 1      # producer stalled → freeze
        return i

    def get_bands(self) -> list[float]:
        with self._lock:
            i = self._index()
            if i is None:
                return [0.0] * NUM_BANDS
            return list(self._history[i].bands)

    def get_wave(self, points: int) -> Optional[list[float]]:
        """The most recent `points` waveform samples ending at the
        consumption clock (~64 points per 23 ms hop)."""
        with self._lock:
            i = self._index()
            if i is None:
                return None
            frames = max(1, math.ceil(points / WAVE_POINTS))
            lo = max(0, i - frames + 1)
            out: list[float] = []
            for k in range(lo, i + 1):
                out.extend(self._history[k].wave)
            return out[-points:] if len(out) >= points else out

    def get_rms(self) -> Optional[float]:
        with self._lock:
            i = self._index()
            if i is None:
                return None
            return self._history[i].rms

    # -------- PCM → frames ---------------------------------------------

    def _drain_stderr(self) -> None:
        """Read stderr line-by-line and log it; prevents the 64 KB
        kernel pipe buffer from filling up and blocking ffmpeg."""
        assert self._proc is not None and self._proc.stderr is not None
        for raw in iter(self._proc.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                log.info("ffmpeg: %s", line)

    def _build_dsp(self):
        window = np.hanning(FFT_SIZE).astype(np.float32)
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE)
        edges = np.logspace(
            np.log10(BAND_LO_HZ), np.log10(BAND_HI_HZ), NUM_BANDS + 1)
        masks = [
            (freqs >= lo) & (freqs < hi)
            for lo, hi in zip(edges[:-1], edges[1:])
        ]
        fftbuf = np.zeros(FFT_SIZE, dtype=np.float32)
        return window, masks, fftbuf

    def _process_pcm(self, chunk: bytes) -> None:
        """One hop of samples → band levels + waveform, appended to
        history. Split out from the read loop so tests can drive it
        with synthetic PCM."""
        if self._dsp is None:
            self._dsp = self._build_dsp()
        window, masks, fftbuf = self._dsp

        samples = (
            np.frombuffer(chunk, dtype=np.int16)
              .astype(np.float32) / 32768.0
        )
        fftbuf[:-HOP_SAMPLES] = fftbuf[HOP_SAMPLES:]
        fftbuf[-HOP_SAMPLES:] = samples

        spec = np.abs(np.fft.rfft(fftbuf * window))
        # Normalize so a full-scale sine lands near 0 dB regardless of
        # FFT size — makes the gate thresholds absolute dBFS-ish values.
        spec /= (FFT_SIZE / 4)

        levels: list[float] = []
        for i, m in enumerate(masks):
            # band max, not mean: high bands span ~100 bins and a mean
            # dilutes real content below the silence gate; the peak bin
            # is band-width-independent so the dB thresholds stay honest
            mag = float(np.max(spec[m])) if m.any() else 0.0
            db = 20.0 * math.log10(mag + 1e-7)
            peak = max(self._band_peak_db[i] - _DB_DECAY_PER_CHUNK, db,
                       SILENCE_DB)
            self._band_peak_db[i] = peak
            if db <= SILENCE_DB:
                target = 0.0
            else:
                target = min(1.0, max(0.0, (db - (peak - DB_RANGE)) / DB_RANGE))
            prev = self._smooth[i]
            alpha = ATTACK if target > prev else RELEASE
            levels.append(prev + (target - prev) * alpha)

        wave = samples.reshape(WAVE_POINTS, -1).mean(axis=1)
        rms = float(np.sqrt(np.mean(samples * samples)))

        with self._lock:
            if self._t0 is None:
                self._t0 = time.monotonic()
            self._smooth = levels
            self._history.append(
                _Frame(list(levels), [float(v) for v in wave], rms))
            self._frames_total += 1

    def _read_pcm(self) -> bool:
        """Read PCM until EOF/stop; returns True if any audio was decoded
        (used by the supervisor to pick the retry backoff)."""
        assert self._proc is not None and self._proc.stdout is not None
        decoded_any = False
        bytes_per_chunk = HOP_SAMPLES * 2
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
            self._process_pcm(bytes(buf))


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


def get_wave(points: int = 256) -> Optional[list[float]]:
    """Recent waveform samples (−1..1), or None when not decoding."""
    if _singleton is None:
        return None
    return _singleton.get_wave(points)


def get_rms() -> Optional[float]:
    """Loudness (0..~1) of the currently-audible hop, or None."""
    if _singleton is None:
        return None
    return _singleton.get_rms()
