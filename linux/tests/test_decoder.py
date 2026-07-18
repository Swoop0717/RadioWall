"""Band-scaling behavior of the FFT decoder: per-band AGC must let
quiet treble reach full range while the silence gate keeps dead bands
dark. Drives _process_pcm directly with synthetic PCM — no ffmpeg."""

import math

import numpy as np
import pytest

from radiowall.audio import decoder
from radiowall.audio.decoder import (
    HOP_SAMPLES, NUM_BANDS, SAMPLE_RATE, WAVE_POINTS, _Decoder,
)


def _pcm_chunk(freqs_amps, n=HOP_SAMPLES, phase=0):
    """s16le mono chunk containing a sum of sines."""
    t = (np.arange(n) + phase) / SAMPLE_RATE
    x = np.zeros(n)
    for f, a in freqs_amps:
        x += a * np.sin(2 * math.pi * f * t)
    return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()


def _feed(d, freqs_amps, chunks=40):
    for k in range(chunks):
        d._process_pcm(_pcm_chunk(freqs_amps, phase=k * HOP_SAMPLES))


def _band_of(freq):
    """Index of the band containing `freq` (mirrors decoder edges)."""
    edges = np.logspace(np.log10(decoder.BAND_LO_HZ),
                        np.log10(decoder.BAND_HI_HZ), NUM_BANDS + 1)
    for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        if lo <= freq < hi:
            return i
    raise AssertionError(f"{freq} Hz outside band range")


def test_quiet_treble_still_reaches_high_levels():
    """A 6 kHz tone 30 dB below the bass must still light its band —
    the old frame-peak normalization kept it near zero."""
    d = _Decoder("test")
    _feed(d, [(120, 0.5), (6000, 0.5 * 10 ** (-30 / 20))])
    bands = d.get_bands()
    assert bands[_band_of(6000)] > 0.6
    assert bands[_band_of(120)] > 0.6


def test_silence_is_gated_dark():
    d = _Decoder("test")
    _feed(d, [])                      # digital silence
    assert all(v < 0.02 for v in d.get_bands())


def test_dead_band_stays_dark_while_music_plays():
    """Bass-only signal: the top bands must not be AGC-boosted noise."""
    d = _Decoder("test")
    _feed(d, [(120, 0.5), (400, 0.3)])
    bands = d.get_bands()
    assert bands[_band_of(120)] > 0.6
    assert bands[NUM_BANDS - 1] < 0.05
    assert bands[NUM_BANDS - 2] < 0.05


def test_wave_and_rms_exposed():
    d = _Decoder("test")
    _feed(d, [(440, 0.5)], chunks=8)
    wave = d.get_wave(256)
    assert wave is not None
    assert len(wave) == 256
    assert max(abs(v) for v in wave) > 0.05
    rms = d.get_rms()
    assert rms == pytest.approx(0.5 / math.sqrt(2), rel=0.1)


def test_wave_shorter_history_returns_what_exists():
    d = _Decoder("test")
    _feed(d, [(440, 0.5)], chunks=2)
    wave = d.get_wave(1024)
    assert wave is not None
    assert len(wave) == 2 * WAVE_POINTS


def test_sync_playback_anchors_consumption_clock():
    """With a curpos sync, the audible frame is picked by the WiiM's
    playback position (extrapolated since the poll), not wall time."""
    import time as _time
    d = _Decoder("test")
    _feed(d, [(440, 0.5)], chunks=100)          # ~2.3 s of stream decoded
    chunk_s = HOP_SAMPLES / SAMPLE_RATE
    now = _time.monotonic()

    d.sync_playback(0.5, now)                   # speaker is at 0.5 s
    with d._lock:
        assert d._index() == int(0.5 / chunk_s)

    d.sync_playback(0.5, now - 1.0)             # polled 1 s ago → 1.5 s
    with d._lock:
        assert d._index() == int(1.5 / chunk_s)

    d.sync_playback(60.0, now)                  # beyond decoded → freeze
    with d._lock:
        assert d._index() == 99


def test_sync_playback_module_fn_is_noop_when_stopped():
    decoder.sync_playback(1.0, 0.0)             # must not raise


def test_all_bands_have_fft_bins():
    """Every log-spaced band must contain at least one FFT bin, else
    it renders permanently dark (regression guard for band layout)."""
    d = _Decoder("test")
    d._dsp = d._build_dsp()
    _window, masks, _buf = d._dsp
    assert all(m.any() for m in masks)
