"""Radio worker: owns all network I/O, driven by a command queue.

The render loop must never block, so every radio.garden/LinkPlay call
happens on this thread. Commands are tiny dataclasses; the queue is
coalesced on drain:

- a newer PlayAt supersedes queued PlayAt/Next commands
- Stop discards everything queued before it
- SetVolume values collapse to the newest, sent to the WiiM only after
  200 ms of quiet (the ESP32 debounce, relocated here)

After a successful play the worker points the visualizer's decoder at
the same resolved stream URL (its own independent ffmpeg connection).

Headless vertical slice:
    python -m radiowall.radio 48.21 16.37
    → plays the nearest city's first station on the WiiM;
      stdin: n = next, v <0-100> = volume, q = stop & quit
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass

from radiowall.audio import decoder
from radiowall.linkplay import LinkPlay
from radiowall.places_db import PlacesDB
from radiowall.radio_garden import RadioGarden
from radiowall.state import AppState, Session

log = logging.getLogger(__name__)

VOL_DEBOUNCE_S = 0.2
DEFAULT_WIIM_IP = "192.168.0.33"


# --- commands ------------------------------------------------------------

@dataclass(frozen=True)
class PlayAt:
    lat: float
    lon: float


@dataclass(frozen=True)
class Next:
    pass


@dataclass(frozen=True)
class Stop:
    pass


@dataclass(frozen=True)
class SetVolume:
    volume: int


Command = PlayAt | Next | Stop | SetVolume


def wiim_ip() -> str:
    return os.getenv("RADIOWALL_WIIM_IP", DEFAULT_WIIM_IP).strip()


class RadioWorker:
    def __init__(self, state: AppState, places: PlacesDB,
                 rg: RadioGarden | None = None,
                 wiim: LinkPlay | None = None,
                 use_decoder: bool = True) -> None:
        self._state = state
        self._places = places
        self._rg = rg or RadioGarden()
        self._wiim = wiim or LinkPlay(wiim_ip())
        self._use_decoder = use_decoder
        self._queue: queue.Queue[Command] = queue.Queue()
        self._session: Session | None = None
        self._running = False
        self._pending_volume: int | None = None
        self._volume_deadline = 0.0
        self._sent_volume: int | None = None
        self._thread = threading.Thread(target=self._loop, name="radio",
                                        daemon=True)

    # --- public API (any thread) ----------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._queue.put(Stop())          # wake the loop
        self._thread.join(timeout=2)

    def submit(self, cmd: Command) -> None:
        self._queue.put(cmd)

    # --- worker thread ----------------------------------------------------

    def _loop(self) -> None:
        self._sync_volume()
        while self._running:
            try:
                cmd = self._queue.get(timeout=0.05)
            except queue.Empty:
                self._flush_volume()
                continue
            if not self._running:
                break
            cmd = self._coalesce(cmd)
            if isinstance(cmd, PlayAt):
                self._handle_play_at(cmd.lat, cmd.lon)
            elif isinstance(cmd, Next):
                self._handle_next()
            elif isinstance(cmd, Stop):
                self._handle_stop()
            self._flush_volume()

    def _absorb_volume(self, cmd: SetVolume) -> None:
        self._pending_volume = cmd.volume
        self._volume_deadline = time.monotonic() + VOL_DEBOUNCE_S

    def _coalesce(self, cmd: Command) -> Command | None:
        """Compact a burst without breaking command order:

        - SetVolume never blocks the queue — absorbed into the debouncer
        - a newer PlayAt or Stop supersedes whatever we were about to do
          (retarget while loading / panic stop)
        - a queued Next after a PlayAt stays queued and runs afterwards

        Returns None when everything absorbed was volume-only.
        """
        if isinstance(cmd, SetVolume):
            self._absorb_volume(cmd)
            cmd = None
        while True:
            try:
                nxt = self._queue.queue[0]          # peek
            except IndexError:
                return cmd
            if isinstance(nxt, SetVolume):
                self._absorb_volume(self._queue.get_nowait())
            elif isinstance(nxt, (PlayAt, Stop)) or cmd is None:
                cmd = self._queue.get_nowait()      # supersede / take first
            else:
                return cmd                          # Next waits its turn

    def _flush_volume(self) -> None:
        if (self._pending_volume is not None
                and time.monotonic() >= self._volume_deadline):
            vol = self._pending_volume
            if vol != self._sent_volume:
                if self._wiim.set_volume(vol):
                    self._sent_volume = vol
                else:
                    log.warning("volume set failed")
            self._pending_volume = None

    def _sync_volume(self) -> None:
        vol = self._wiim.get_volume()
        if vol is not None:
            self._sent_volume = vol
            self._state.set_volume(vol)
            log.info("WiiM volume: %d", vol)

    # --- handlers -------------------------------------------------------

    def _handle_play_at(self, lat: float, lon: float) -> None:
        place = self._places.find_nearest(lat, lon)
        if place is None:
            self._state.set_status("No places database")
            return
        log.info("touch (%.2f, %.2f) -> %s, %s", lat, lon,
                 place.name, place.country)
        self._state.set_loading(place.name, place.country)
        stations = self._rg.get_stations(place.id)
        if not stations:
            self._state.set_status("No stations found")
            self._to_idle_or_playing()
            return
        self._session = Session(origin_lat=lat, origin_lon=lon,
                                place=place, stations=stations)
        self._play_next_in_session()

    def _handle_next(self) -> None:
        if self._session is None:
            self._state.set_status("Nothing playing")
            return
        if self._session.exhausted and not self._hop_city():
            return
        self._play_next_in_session()

    def _hop_city(self) -> bool:
        s = self._session
        if not s.can_hop:
            self._state.set_status("No more stations")
            return False
        place = self._places.find_nearest_excluding(
            s.origin_lat, s.origin_lon, s.visited)
        if place is None:
            self._state.set_status("No more stations")
            return False
        log.info("city hop -> %s, %s (%d visited)",
                 place.name, place.country, len(s.visited))
        self._state.set_loading(place.name, place.country)
        stations = self._rg.get_stations(place.id)
        if not stations:
            # Mark visited WITHOUT entering: the previous station is still
            # audibly playing and its info must survive on screen. The next
            # NEXT skips this city via the visited set.
            s.visited.add(place.id)
            self._to_idle_or_playing()      # un-stick the "Tuning..." phase
            self._state.set_status("No stations found")   # after: set_playing clears status
            return False
        s.enter_city(place, stations)
        return True

    def _play_next_in_session(self) -> None:
        s = self._session
        if s.exhausted:
            self._state.set_status("No more stations")
            return
        station = s.advance()
        self._state.set_loading(s.place.name, s.place.country)
        stream_url = self._rg.resolve_stream_url(station.id)
        if not stream_url:
            self._state.set_status("Failed to play")
            self._to_idle_or_playing()
            return
        if not self._wiim.play(stream_url):
            self._state.set_status("Failed to play")
            self._to_idle_or_playing()
            return
        self._state.set_playing(s.place.name, s.place.country, station.title,
                                s.playing_index + 1, len(s.stations))
        log.info("playing %d/%d: %s (%s)", s.playing_index + 1,
                 len(s.stations), station.title, s.place.name)
        if self._use_decoder:
            decoder.stop()
            decoder.start(stream_url)

    def _handle_stop(self) -> None:
        if self._use_decoder:
            decoder.stop()
        self._wiim.stop()
        self._session = None
        self._state.set_idle()
        log.info("stopped")

    def _to_idle_or_playing(self) -> None:
        """After a failure, fall back to reflecting what's actually true."""
        s = self._session
        station = s.current_station() if s else None
        if s and station:
            self._state.set_playing(s.place.name, s.place.country,
                                    station.title, s.playing_index + 1,
                                    len(s.stations))
        else:
            self._state.set_idle()


def _main() -> int:
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    if len(sys.argv) != 3:
        print("usage: python -m radiowall.radio <lat> <lon>")
        return 2

    from radiowall import places_db

    state = AppState()
    places = PlacesDB.load(places_db.default_path())
    worker = RadioWorker(state, places, use_decoder=False)
    worker.start()
    worker.submit(PlayAt(float(sys.argv[1]), float(sys.argv[2])))

    print("commands: n = next station, v <0-100> = volume, q = quit")
    try:
        for line in sys.stdin:
            line = line.strip()
            if line == "n":
                worker.submit(Next())
            elif line.startswith("v "):
                worker.submit(SetVolume(int(line[2:])))
            elif line == "q":
                break
            snap = state.snapshot()
            print(f"  [{snap.phase.value}] {snap.place_name} — "
                  f"{snap.station_title} ({snap.station_index}/"
                  f"{snap.station_total}) vol={snap.volume}")
    except KeyboardInterrupt:
        pass
    finally:
        worker.submit(Stop())
        time.sleep(0.5)
        worker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
