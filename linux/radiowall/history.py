"""Playback history + favorites, persisted next to the config store.

Every station that plays for RECORD_AFTER_S gets recorded (the
threshold keeps NEXT-skipping sprees out). A favorite is just a pinned
entry: starred rows are exempt from the size cap and never age out.
Stream URLs are deliberately NOT stored — they rot within weeks;
replay re-resolves through the normal Radio.garden flow.

Thread-safety mirrors radiowall.config: one module lock, atomic writes.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field

from radiowall import config

log = logging.getLogger(__name__)

RECORD_AFTER_S = 30.0
MAX_ENTRIES = 50               # favorites don't count against this

_lock = threading.Lock()
_cache: list["Entry"] | None = None


@dataclass
class Entry:
    station_id: str
    station_title: str
    place_id: str
    place_name: str
    country: str               # ISO code, same as Place.country
    lat: float
    lon: float
    ts: float = field(default_factory=time.time)
    favorite: bool = False


def _path():
    return config.path().parent / "history.json"


def _load() -> list[Entry]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        raw = json.loads(_path().read_text())
        _cache = [Entry(**e) for e in raw]
    except FileNotFoundError:
        _cache = []
    except (OSError, ValueError, TypeError) as e:
        log.warning("history unreadable (%s); starting empty", e)
        _cache = []
    return _cache


def _save(entries: list[Entry]) -> None:
    p = _path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(e) for e in entries], indent=1))
        os.replace(tmp, p)
    except OSError as e:
        log.error("history save failed: %s", e)


def add(entry: Entry) -> None:
    """Record a played station. Replaying a known station moves it to
    the top (fresh timestamp) and keeps its favorite flag."""
    with _lock:
        entries = _load()
        for old in entries:
            if old.station_id == entry.station_id:
                entry.favorite = old.favorite
                entries.remove(old)
                break
        entries.insert(0, entry)
        # trim oldest non-favorites beyond the cap
        plain = [e for e in entries if not e.favorite]
        for e in plain[MAX_ENTRIES:]:
            entries.remove(e)
        _save(entries)
        log.info("history: recorded %s (%s)",
                 entry.station_title, entry.place_name)


def entries(favorites_only: bool = False) -> list[Entry]:
    """Newest first; favorites keep their place in the timeline."""
    with _lock:
        out = list(_load())
    if favorites_only:
        out = [e for e in out if e.favorite]
    return out


def toggle_favorite(station_id: str) -> bool:
    """Flip the star; returns the new state (False if id unknown)."""
    with _lock:
        entries_ = _load()
        for e in entries_:
            if e.station_id == station_id:
                e.favorite = not e.favorite
                _save(entries_)
                return e.favorite
    return False


def reset_cache_for_tests() -> None:
    global _cache
    with _lock:
        _cache = None
