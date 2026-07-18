"""Application state: what the UI renders, and the station/city session.

Two layers, both here because both are pure and unit-testable:

- `AppState` / `Snapshot`: thread-safe UI-facing state. The radio worker
  mutates it via setters; the render loop calls `snapshot()` once per
  frame and draws from the frozen copy. One lock, held only for field
  copies — never across I/O.

- `Session`: the NEXT/city-hop bookkeeping, ported from the ESP32
  radio_client. Cycle through the current city's stations; when
  exhausted, hop to the next-nearest *unvisited* city measured from the
  ORIGINAL touch point (not the current city), up to MAX_CITIES total.
  Pure data — the worker does the I/O between `Session` steps.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from enum import Enum

from radiowall.places_db import Place
from radiowall.radio_garden import Station

MAX_CITIES = 20          # visited-city cap per touch (ESP32 parity)
STATUS_TTL_S = 3.0
VOLUME_FLASH_S = 1.5


class Phase(Enum):
    IDLE = "idle"
    LOADING = "loading"
    PLAYING = "playing"
    # PAUSED reserved for v2 — linkplay.pause/resume already exist.


@dataclass(frozen=True)
class Snapshot:
    phase: Phase = Phase.IDLE
    place_name: str = ""
    country: str = ""
    station_title: str = ""
    station_index: int = 0        # 1-based; 0 = none
    station_total: int = 0
    volume: int = 50
    status_text: str = ""         # transient; "" = none (expiry pre-applied)
    volume_flash: bool = False    # show the volume overlay this frame
    sleep_min_left: int = 0       # armed sleep timer, minutes left (0 = off)
    track_title: str = ""         # ICY now-playing ("" = station sends none)


class AppState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snap = Snapshot()
        self._status_until = 0.0
        self._flash_until = 0.0
        self._sleep_deadline: float | None = None

    # --- worker-side setters -------------------------------------------

    def set_loading(self, place_name: str, country: str) -> None:
        with self._lock:
            self._snap = replace(self._snap, phase=Phase.LOADING,
                                 place_name=place_name, country=country,
                                 station_title="", station_index=0,
                                 station_total=0)

    def set_playing(self, place_name: str, country: str, station_title: str,
                    index: int, total: int) -> None:
        with self._lock:
            self._snap = replace(self._snap, phase=Phase.PLAYING,
                                 place_name=place_name, country=country,
                                 station_title=station_title,
                                 station_index=index, station_total=total,
                                 track_title="")
            self._status_until = 0.0

    def set_idle(self) -> None:
        # Keep volume AND any transient status ("No stations found" must
        # survive the fall-back to idle that immediately follows it).
        with self._lock:
            self._snap = Snapshot(volume=self._snap.volume,
                                  status_text=self._snap.status_text)

    def set_status(self, text: str, ttl_s: float = STATUS_TTL_S) -> None:
        with self._lock:
            self._snap = replace(self._snap, status_text=text)
            self._status_until = time.monotonic() + ttl_s

    def set_volume(self, volume: int) -> None:
        with self._lock:
            self._snap = replace(self._snap, volume=max(0, min(100, volume)))

    def set_sleep(self, deadline: float | None) -> None:
        """Arm/disarm the sleep-timer countdown (monotonic deadline)."""
        with self._lock:
            self._sleep_deadline = deadline

    def set_track(self, title: str) -> None:
        """ICY now-playing title (fed from the decoder by the render
        loop; no-op unless it changed)."""
        with self._lock:
            if self._snap.track_title != title:
                self._snap = replace(self._snap, track_title=title)

    # --- UI-side helpers ------------------------------------------------

    def bump_volume(self, delta: int) -> int:
        """Adjust volume from the UI thread; returns the new value."""
        with self._lock:
            vol = max(0, min(100, self._snap.volume + delta))
            self._snap = replace(self._snap, volume=vol)
            self._flash_until = time.monotonic() + VOLUME_FLASH_S
            return vol

    def snapshot(self) -> Snapshot:
        now = time.monotonic()
        with self._lock:
            snap = self._snap
            status = snap.status_text if now < self._status_until else ""
            sleep_left = 0
            if self._sleep_deadline is not None and self._sleep_deadline > now:
                sleep_left = int((self._sleep_deadline - now) // 60) + 1
            return replace(snap, status_text=status,
                           volume_flash=now < self._flash_until,
                           sleep_min_left=sleep_left)


@dataclass
class Session:
    """One touch's playback session: station cursor + city-hop state."""
    origin_lat: float
    origin_lon: float
    place: Place
    stations: list[Station]
    next_index: int = 0                       # next station to play (0-based)
    playing_index: int = -1                   # currently playing (-1 = none)
    visited: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.visited.add(self.place.id)

    @property
    def exhausted(self) -> bool:
        """True when the current city has no unplayed stations left."""
        return self.next_index >= len(self.stations)

    @property
    def can_hop(self) -> bool:
        return len(self.visited) < MAX_CITIES

    def current_station(self) -> Station | None:
        if 0 <= self.playing_index < len(self.stations):
            return self.stations[self.playing_index]
        return None

    def advance(self) -> Station:
        """Mark the next station as playing and return it. Caller ensures
        not `exhausted`. Always advances the cursor, even if the caller's
        stream-resolve later fails — matching the ESP32 (failed stations
        are skipped, not retried)."""
        station = self.stations[self.next_index]
        self.playing_index = self.next_index
        self.next_index += 1
        return station

    def enter_city(self, place: Place, stations: list[Station]) -> None:
        """Hop: replace the current city, keep origin + visited set."""
        self.place = place
        self.stations = stations
        self.next_index = 0
        self.playing_index = -1
        self.visited.add(place.id)
