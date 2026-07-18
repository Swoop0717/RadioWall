"""Bluetooth output: the board decodes the stream and pushes PCM to a
BT speaker via bluealsa (A2DP source).

Same duck-typed surface as LinkPlay — play/stop/set_volume/get_volume —
so the RadioWorker treats a BtPlayer exactly like a WiiM. The optional
LinkPlay extras (get_position, set_sleep_timer) are deliberately
absent: without them the visualizer runs live (BT latency is a few
hundred ms, close enough) and the sleep timer relies on the worker's
local deadline, which stops this player just fine.

Unlike the WiiM (which pulls the stream itself and rides out network
blips with its own buffer), here ffmpeg IS the player, so a supervisor
thread restarts it if the stream or the BT link hiccups.

Volume goes through bluealsa's ALSA mixer ("<name> - A2DP" simple
control); if the mixer isn't available the volume calls report failure
and the UI shows its usual warning.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time

from radiowall import btaudio

log = logging.getLogger(__name__)

_VOL_RE = re.compile(r"\[(\d{1,3})%\]")


class BtPlayer:
    def __init__(self, mac: str, name: str = "") -> None:
        self.mac = mac.upper()
        self.name = name or self.mac
        self._url: str | None = None
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._generation = 0

    # -------- LinkPlay-compatible surface --------------------------------

    def play(self, url: str) -> bool:
        if not shutil.which("ffmpeg"):
            log.error("ffmpeg missing — cannot play via Bluetooth")
            return False
        ok, msg = btaudio.connect(self.mac)
        if not ok:
            log.warning("bt speaker %s unreachable: %s", self.name, msg)
            return False
        with self._lock:
            self._url = url
            self._generation += 1
            gen = self._generation
        self._kill_proc()
        if not self._spawn_if_current(url, gen):
            return False
        # one supervisor per generation; stale ones exit on the gen check
        threading.Thread(target=self._supervise, args=(gen,),
                         name="btplayer", daemon=True).start()
        return True

    def stop(self) -> bool:
        with self._lock:
            self._url = None
            self._generation += 1
        self._kill_proc()
        return True

    def close(self) -> None:
        """Called by the worker when the output is swapped away from
        this instance. MUST kill our ffmpeg: the bluealsa PCM is
        exclusive, and an orphaned instance blocks the successor with
        'Device or resource busy' forever."""
        self.stop()

    def set_volume(self, vol: int) -> bool:
        vol = max(0, min(100, int(vol)))
        rc = subprocess.run(
            ["amixer", "-D", "bluealsa", "sset",
             f"{self.name} - A2DP", f"{vol}%"],
            capture_output=True, text=True).returncode
        return rc == 0

    def get_volume(self) -> int | None:
        try:
            p = subprocess.run(
                ["amixer", "-D", "bluealsa", "sget",
                 f"{self.name} - A2DP"],
                capture_output=True, text=True, timeout=5)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        m = _VOL_RE.search(p.stdout)
        return int(m.group(1)) if p.returncode == 0 and m else None

    # -------- internals ----------------------------------------------------

    def _spawn_if_current(self, url: str, gen: int) -> bool:
        """Spawn ffmpeg, then commit it only if this generation still
        owns the player — a concurrent play()/stop()/close() may have
        superseded us while Popen was underway. A stale process is
        killed instantly so it can never squat on the exclusive PCM."""
        device = f"bluealsa:DEV={self.mac},PROFILE=a2dp"
        proc = subprocess.Popen(
            [
                "ffmpeg", "-nostdin", "-loglevel", "warning",
                "-user_agent", "VLC/3.0.20 LibVLC/3.0.20",
                "-reconnect", "1", "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-i", url,
                "-f", "alsa", device,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        with self._lock:
            if self._generation != gen or self._url is None:
                try:
                    proc.kill()
                except Exception:
                    pass
                return False
            self._proc = proc
        threading.Thread(target=self._drain_stderr, args=(proc,),
                         name="btplayer-stderr", daemon=True).start()
        log.info("bt playback started: %s -> %s", url, self.name)
        return True

    @staticmethod
    def _drain_stderr(proc: subprocess.Popen) -> None:
        """ffmpeg problems (dead stream, ALSA/BT failures) must reach
        the journal — losing them to /dev/null cost a debugging session."""
        assert proc.stderr is not None
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                log.info("bt ffmpeg: %s", line)

    def _kill_proc(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass

    def _supervise(self, gen: int) -> None:
        """Respawn ffmpeg if it dies while this generation's URL is
        still wanted. Every step re-checks the generation — the fatal
        variant of this loop once spawned a second ffmpeg after a slow
        btaudio.connect() raced a new play(), and the two instances
        deadlocked on the exclusive PCM ('Device or resource busy')."""
        backoff = 2.0
        while True:
            with self._lock:
                proc = self._proc if self._generation == gen else None
            if proc is None:
                return
            proc.wait()
            with self._lock:
                if self._generation != gen or self._url is None:
                    return                 # stopped or replaced
                url = self._url
            log.info("bt player exited — retrying in %.0fs", backoff)
            time.sleep(backoff)
            with self._lock:
                if self._generation != gen or self._url is None:
                    return
            btaudio.connect(self.mac)      # BT link may have dropped too
            if not self._spawn_if_current(url, gen):
                return                     # superseded during connect
            backoff = min(backoff * 2, 30.0)
