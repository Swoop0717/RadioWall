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


def test_stream_title_parsed_and_revealed_live():
    d = _Decoder("test")
    _feed(d, [(440, 0.5)], chunks=10)
    assert d._ingest_stderr_line(
        "[https @ 0x55] Metadata update for StreamTitle: Artist - Song") \
        is True
    assert d._ingest_stderr_line("random ffmpeg noise") is False
    # live path (no sync, VIS_DELAY 0): visible immediately
    assert d.get_stream_title() == "Artist - Song"


def test_stream_title_waits_for_consumption_clock():
    import time as _time
    d = _Decoder("test")
    _feed(d, [(440, 0.5)], chunks=100)       # ~2.3 s decoded
    # title arrived at decode position ~2.3 s (frame 100)
    d._ingest_stderr_line("Metadata update for StreamTitle: New Song")
    now = _time.monotonic()
    d.sync_playback(0.5, now)                # speaker only at 0.5 s
    assert d.get_stream_title() == ""        # not audible yet
    d.sync_playback(2.4, now)                # speaker caught up
    assert d.get_stream_title() == "New Song"


def test_stream_title_keeps_latest_audible_of_many():
    d = _Decoder("test")
    _feed(d, [(440, 0.5)], chunks=5)
    d._ingest_stderr_line("Metadata update for StreamTitle: One")
    _feed(d, [(440, 0.5)], chunks=5)
    d._ingest_stderr_line("Metadata update for StreamTitle: Two")
    assert d.get_stream_title() == "Two"     # live: newest audible wins


def test_icy_consume_parses_titles_from_metaint_stream():
    import io

    def meta_block(text):
        payload = f"StreamTitle='{text}';".encode()
        k = (len(payload) + 15) // 16
        return bytes([k]) + payload.ljust(k * 16, b"\x00")

    metaint = 32
    stream = (b"A" * metaint + meta_block("Song One")
              + b"B" * metaint + bytes([0])          # empty metadata block
              + b"C" * metaint + meta_block("Song Two"))

    d = _Decoder("test")
    _feed(d, [(440, 0.5)], chunks=2)
    d._icy_consume(io.BytesIO(stream), metaint)
    assert d.get_stream_title() == "Song Two"
    titles = [t for _i, t in d._titles]
    assert titles == ["Song One", "Song Two"]


def test_icy_duplicate_titles_dropped():
    d = _Decoder("test")
    _feed(d, [(440, 0.5)], chunks=2)
    d._note_title("Same Song")
    d._note_title("Same Song")               # e.g. stderr echo of source 1
    assert len(d._titles) == 1
