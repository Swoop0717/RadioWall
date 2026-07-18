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

from radiowall import history
from radiowall.audio import decoder
from radiowall.linkplay import LinkPlay
from radiowall.places_db import Place, PlacesDB, country_name
from radiowall.radio_garden import RadioGarden, Station
from radiowall.state import AppState, Session

log = logging.getLogger(__name__)

VOL_DEBOUNCE_S = 0.2

# Visualizer sync polling: after a play command, poll the WiiM's curpos
# often (it locks the visualizer to the speaker as soon as sound starts),
# then back off to an occasional drift check.
SYNC_FAST_S = 2.0
SYNC_SLOW_S = 10.0
SYNC_FAST_WINDOW_S = 30.0

# Silent-station skip: some streams connect fine but carry no audio at
# all. Evaluated ONCE per station, ~20 s in: enough decoded audio with
# a peak RMS below the floor (digital silence ~1e-5, quiet speech
# ~0.05) → auto-NEXT. Checked before the 30 s history threshold, so
# skipped duds are never recorded.
SILENT_CHECK_AT_S = 20.0
SILENT_MIN_DECODED_S = 10.0
SILENCE_RMS = 0.0015


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


@dataclass(frozen=True)
class SetSleep:
    minutes: int          # 0 = cancel


@dataclass(frozen=True)
class PlayEntry:
    """Replay a history/favorites entry. Re-resolves the stream via
    Radio.garden; a full Session is rebuilt from the stored place so
    NEXT keeps its city-hop semantics after a replay."""
    entry: history.Entry


@dataclass(frozen=True)
class FavoriteCurrent:
    """Triple-press: toggle the currently playing station's star."""
    pass


Command = (PlayAt | Next | Stop | SetVolume | SetSleep | PlayEntry
           | FavoriteCurrent)


def wiim_ip() -> str:
    """Speaker address: env override > config store (set by the on-device
    setup UI) > empty. Empty means 'not configured yet' — the worker
    then tells the user to run setup instead of poking a dead IP."""
    env = os.getenv("RADIOWALL_WIIM_IP", "").strip()
    if env:
        return env
    from radiowall import config
    return str(config.get("wiim_ip") or "").strip()


class RadioWorker:
    def __init__(self, state: AppState, places: PlacesDB,
                 rg: RadioGarden | None = None,
                 wiim: LinkPlay | None = None,
                 use_decoder: bool = True) -> None:
        self._state = state
        self._places = places
        self._rg = rg or RadioGarden()
        if wiim is not None:
            self._wiim: object | None = wiim
        else:
            self._wiim = self._make_output()
            if self._wiim is None:
                log.warning("no speaker configured — hold the knob for setup")
        self._use_decoder = use_decoder
        self._queue: queue.Queue[Command] = queue.Queue()
        self._session: Session | None = None
        self._running = False
        self._pending_volume: int | None = None
        self._volume_deadline = 0.0
        self._sent_volume: int | None = None
        self._played_at = 0.0            # monotonic time of last play cmd
        self._sync_logged = False        # one "synced" log line per station
        self._sleep_deadline: float | None = None
        self._record_after_s = history.RECORD_AFTER_S
        self._pending_record: history.Entry | None = None
        self._record_at = 0.0
        self._current_entry: history.Entry | None = None
        self._silent_check_at_s = SILENT_CHECK_AT_S
        self._silent_checked = 0.0       # played_at already evaluated
        self._sync_fast_s = SYNC_FAST_S  # instance attrs so tests can shrink
        self._sync_slow_s = SYNC_SLOW_S
        self._thread = threading.Thread(target=self._loop, name="radio",
                                        daemon=True)
        self._sync_thread = threading.Thread(
            target=self._sync_loop, name="vis-sync", daemon=True)

    # --- public API (any thread) ----------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread.start()
        if self._use_decoder:
            self._sync_thread.start()

    def stop(self, stop_playback: bool = False) -> None:
        """Shut the worker down. With stop_playback=True (natural program
        exit) the WiiM is silenced too — a stopped RadioWall should not
        leave the radio playing forever."""
        self._running = False
        self._queue.put(Stop())          # wake the loop
        self._thread.join(timeout=2)
        if stop_playback and self._session is not None:
            if self._use_decoder:
                decoder.stop()
            if self._wiim is not None:
                self._wiim.stop()
            log.info("playback stopped on exit")

    def submit(self, cmd: Command) -> None:
        self._queue.put(cmd)

    def set_sleep_timer(self, minutes: int) -> None:
        """Arm (or cancel with 0) the sleep timer — menu entry point."""
        self.submit(SetSleep(minutes))

    def stop_playback(self) -> None:
        """Menu 'Stop' entry point."""
        self.submit(Stop())

    def play_history(self, entry: history.Entry) -> None:
        """Menu History/Favorites entry point."""
        self.submit(PlayEntry(entry))

    def favorite_current(self) -> None:
        """Triple-press entry point."""
        self.submit(FavoriteCurrent())

    def sleep_minutes_left(self) -> int:
        """Minutes until the armed sleep timer fires (0 = not armed)."""
        deadline = self._sleep_deadline
        if deadline is None:
            return 0
        left = deadline - time.monotonic()
        return int(left // 60) + 1 if left > 0 else 0

    @staticmethod
    def _make_output():
        """Build the output client from config: WiiM (LinkPlay) or a
        Bluetooth speaker (BtPlayer — board decodes, bluealsa sends).
        RADIOWALL_WIIM_IP still forces the WiiM path for dev setups."""
        from radiowall import config
        if (not os.getenv("RADIOWALL_WIIM_IP", "").strip()
                and config.get("output") == "bt" and config.get("bt_mac")):
            from radiowall.btplayer import BtPlayer
            return BtPlayer(str(config.get("bt_mac")),
                            str(config.get("bt_name") or ""))
        ip = wiim_ip()
        return LinkPlay(ip) if ip else None

    def _close_output(self) -> None:
        """A BtPlayer being swapped away MUST release its ffmpeg — the
        bluealsa PCM is exclusive and an orphan blocks the successor.
        (LinkPlay clients have no close(); nothing to release.)"""
        close = getattr(self._wiim, "close", None)
        if close is not None:
            close()

    def set_wiim(self, ip: str) -> None:
        """Swap to a WiiM speaker (called by the setup UI). Local-only
        work — safe on the render thread."""
        self._close_output()
        self._wiim = LinkPlay(ip)
        self._sent_volume = None
        log.info("speaker set to WiiM %s", ip)

    def set_bt(self, mac: str, name: str = "") -> None:
        """Swap output to a Bluetooth speaker."""
        from radiowall.btplayer import BtPlayer
        self._close_output()
        self._wiim = BtPlayer(mac, name)
        self._sent_volume = None
        log.info("speaker set to BT %s (%s)", name or mac, mac)

    # --- worker thread ----------------------------------------------------

    def _loop(self) -> None:
        self._sync_volume()
        while self._running:
            try:
                cmd = self._queue.get(timeout=0.05)
            except queue.Empty:
                self._flush_volume()
                self._check_sleep()
                self._check_record()
                self._check_silent()
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
            elif isinstance(cmd, SetSleep):
                self._handle_sleep(cmd.minutes)
            elif isinstance(cmd, PlayEntry):
                self._handle_play_entry(cmd.entry)
            elif isinstance(cmd, FavoriteCurrent):
                self._handle_favorite()
            self._flush_volume()
            self._check_sleep()
            self._check_record()
            self._check_silent()

    def _sync_loop(self) -> None:
        """Poll the WiiM's playback position and hand it to the decoder,
        which anchors the visualizer's consumption clock to what the
        speaker is actually playing (replaces guessing VIS_DELAY). Own
        thread: getPlayerStatus can block for seconds and must never
        stall touch handling on the worker thread."""
        last_poll = 0.0
        while self._running:
            time.sleep(min(0.25, self._sync_fast_s / 4))
            now = time.monotonic()
            if self._session is None:
                continue
            # looked up per-iteration: the setup UI can swap the speaker
            # at runtime, and fakes/tests may not have the method at all
            get_position = getattr(self._wiim, "get_position", None)
            if get_position is None:
                continue
            fast = now - self._played_at < SYNC_FAST_WINDOW_S
            interval = self._sync_fast_s if fast else self._sync_slow_s
            # a fresh play command restarts the cadence immediately
            if now - max(last_poll, self._played_at) < interval:
                continue
            last_poll = now
            t0 = now
            result = get_position()
            if result is None:
                continue
            status, pos_s = result
            # curpos stays 0 while the WiiM is still buffering; syncing
            # then would freeze the visualizer on the burst start.
            if status != "play" or pos_s <= 0:
                continue
            # position was true somewhere inside the HTTP round trip
            measured_at = (t0 + time.monotonic()) / 2
            decoder.sync_playback(pos_s, measured_at)
            if not self._sync_logged:
                self._sync_logged = True
                log.info("visualizer synced to WiiM position %.1fs", pos_s)

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
            if self._wiim is None:
                self._pending_volume = None
                return
            if vol != self._sent_volume:
                if self._wiim.set_volume(vol):
                    self._sent_volume = vol
                else:
                    log.warning("volume set failed")
            self._pending_volume = None

    def _sync_volume(self) -> None:
        if self._wiim is None:
            return
        vol = self._wiim.get_volume()
        if vol is not None:
            self._sent_volume = vol
            self._state.set_volume(vol)
            log.info("WiiM volume: %d", vol)

    # --- handlers -------------------------------------------------------

    _DEAD_TAP_HOPS = 5      # empty cities tried before giving up

    def _handle_play_at(self, lat: float, lon: float) -> None:
        place = self._places.find_nearest(lat, lon)
        if place is None:
            self._state.set_status("No places database")
            return
        log.info("touch (%.2f, %.2f) -> %s, %s", lat, lon,
                 place.name, place.country)
        self._state.set_loading(place.name, country_name(place.country))
        stations = self._rg.get_stations(place.id)

        # dead-tap auto-hop: a city can lose its stations between the
        # weekly places refreshes — the map must never feel broken, so
        # silently try the next-nearest cities instead of giving up
        visited = {place.id}
        hops = 0
        while not stations and hops < self._DEAD_TAP_HOPS:
            nxt = self._places.find_nearest_excluding(lat, lon, visited)
            if nxt is None:
                break
            log.info("no stations in %s — hopping to %s, %s",
                     place.name, nxt.name, nxt.country)
            place = nxt
            visited.add(place.id)
            self._state.set_loading(place.name, country_name(place.country))
            stations = self._rg.get_stations(place.id)
            hops += 1

        if not stations:
            self._state.set_status("No stations found")
            self._to_idle_or_playing()
            return
        self._session = Session(origin_lat=lat, origin_lon=lon,
                                place=place, stations=stations)
        self._session.visited.update(visited)   # NEXT skips the duds too
        self._play_next_in_session()

    def _handle_next(self) -> None:
        if self._session is None:
            # idle tap = resume: bring back the most recent station
            # instead of shrugging with "Nothing playing"
            entries = history.entries()
            if entries:
                log.info("idle NEXT -> resuming %s",
                         entries[0].station_title)
                self._handle_play_entry(entries[0])
            else:
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
        self._state.set_loading(place.name, country_name(place.country))
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
        if self._wiim is None:
            self._state.set_status("No speaker — hold knob for setup")
            self._state.set_idle()
            return
        self._state.set_loading(s.place.name, country_name(s.place.country))
        stream_url = self._rg.resolve_stream_url(station.id)
        if not stream_url:
            self._state.set_status("Failed to play")
            self._to_idle_or_playing()
            return
        if not self._wiim.play(stream_url):
            self._state.set_status("Failed to play")
            self._to_idle_or_playing()
            return
        self._state.set_playing(s.place.name, country_name(s.place.country),
                                station.title,
                                s.playing_index + 1, len(s.stations))
        log.info("playing %d/%d: %s (%s)", s.playing_index + 1,
                 len(s.stations), station.title, s.place.name)
        if self._use_decoder:
            decoder.stop()
            decoder.start(stream_url)
        self._played_at = time.monotonic()
        self._sync_logged = False
        # history: record only stations that survive the skip window
        self._pending_record = history.Entry(
            station_id=station.id, station_title=station.title,
            place_id=s.place.id, place_name=s.place.name,
            country=s.place.country,
            lat=s.place.lat100 / 100.0, lon=s.place.lon100 / 100.0)
        self._current_entry = self._pending_record
        self._record_at = self._played_at + self._record_after_s

    def _handle_sleep(self, minutes: int) -> None:
        """Arm/cancel the sleep timer. Belt and braces: the WiiM gets its
        native setSleepTimer too (a few seconds later than ours, so we
        normally stop it first), so the music dies on time even if this
        board hangs. The timer survives station changes and manual stops
        by design — 'off in 60 min' means off in 60, whatever you tune
        to meanwhile. Only 'Off' disarms it."""
        native = getattr(self._wiim, "set_sleep_timer", None)
        if minutes <= 0:
            self._sleep_deadline = None
            self._state.set_sleep(None)
            if native:
                native(0)
            self._state.set_status("Sleep timer off")
            log.info("sleep timer cancelled")
        else:
            self._sleep_deadline = time.monotonic() + minutes * 60
            self._state.set_sleep(self._sleep_deadline)
            if native:
                native(minutes * 60 + 10)
            self._state.set_status(f"Sleep in {minutes} min")
            log.info("sleep timer armed: %d min", minutes)

    def _check_sleep(self) -> None:
        if (self._sleep_deadline is not None
                and time.monotonic() >= self._sleep_deadline):
            log.info("sleep timer expired — stopping")
            self._sleep_deadline = None
            self._state.set_sleep(None)
            self._handle_stop()
            self._state.set_status("Good night", ttl_s=10.0)

    def _handle_play_entry(self, entry: history.Entry) -> None:
        """Replay from history: rebuild a real Session anchored at the
        stored place so NEXT hops cities exactly like after a touch."""
        place = Place(id=entry.place_id,
                      lat100=int(entry.lat * 100),
                      lon100=int(entry.lon * 100),
                      name=entry.place_name, country=entry.country)
        station = Station(id=entry.station_id, title=entry.station_title)
        self._session = Session(origin_lat=entry.lat, origin_lon=entry.lon,
                                place=place, stations=[station])
        self._play_next_in_session()

    def _handle_favorite(self) -> None:
        """Star (or unstar) whatever is playing right now. Records the
        station immediately — a triple-press is a stronger signal than
        surviving the 30 s window."""
        e = self._current_entry
        if e is None:
            self._state.set_status("Nothing playing")
            return
        history.add(e)
        starred = history.toggle_favorite(e.station_id)
        self._state.set_status(
            ("★ " if starred else "unstarred ") + e.station_title)
        log.info("favorite %s: %s", "on" if starred else "off",
                 e.station_title)

    def _check_record(self) -> None:
        if (self._pending_record is not None
                and time.monotonic() >= self._record_at):
            history.add(self._pending_record)
            self._pending_record = None

    def _check_silent(self) -> None:
        """Once per station, ~20 s in: skip streams that connect but
        deliver only digital silence. Uses the decoder tap's loudness —
        the WiiM plays the same bytes, silence is silence."""
        if (not self._use_decoder or self._session is None
                or self._silent_checked == self._played_at
                or time.monotonic() - self._played_at < self._silent_check_at_s):
            return
        self._silent_checked = self._played_at
        stats = decoder.get_stats()
        if stats is None:
            return
        seconds, peak = stats
        if seconds >= SILENT_MIN_DECODED_S and peak < SILENCE_RMS:
            log.info("silent stream (%.0fs decoded, peak rms %.5f) — "
                     "skipping", seconds, peak)
            self._state.set_status("Silent stream — next")
            self._handle_next()

    def _handle_stop(self) -> None:
        if self._use_decoder:
            decoder.stop()
        if self._wiim is not None:
            self._wiim.stop()
        self._session = None
        self._pending_record = None
        self._current_entry = None
        self._state.set_idle()
        log.info("stopped")

    def _to_idle_or_playing(self) -> None:
        """After a failure, fall back to reflecting what's actually true."""
        s = self._session
        station = s.current_station() if s else None
        if s and station:
            self._state.set_playing(s.place.name, country_name(s.place.country),
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
