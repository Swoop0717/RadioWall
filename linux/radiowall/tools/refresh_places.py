"""Refresh places.bin from Radio.garden — run weekly by
radiowall-places.timer on the board.

Radio.garden's place list churns ~3%/week (measured 2026-07-18:
184 added + 169 removed in 5 days). Stale-removed places are the
painful kind — a tap resolves to a city whose station list comes back
empty. This job re-downloads the list, rebuilds the binary in the same
RGPL format as tools/compile_places.py, sanity-checks it, and swaps it
atomically (previous file kept as places.bin.bak).

The running app keeps its in-memory copy; --restart-if-idle restarts
the service to pick the file up ONLY when the speaker isn't playing
(never interrupt music for housekeeping — the next natural restart
gets it otherwise).

    python -m radiowall.tools.refresh_places [--restart-if-idle] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import requests

from radiowall import places_db
from radiowall.places_db import PlacesDB

log = logging.getLogger(__name__)

PLACES_URL = "http://radio.garden/api/ara/content/places"
USER_AGENT = "RadioWall/1.0 (places refresh)"
MAGIC = b"RGPL"
VERSION = 1

# A fresh list must be plausibly complete before it replaces a working
# one — a truncated download or an API hiccup must never shrink the map.
MIN_COUNT = 8000
MIN_RATIO_OF_OLD = 0.9

# Copied from tools/compile_places.py (the dev-side ESP32 compiler —
# not deployed to the board, hence the duplication): radio.garden's
# nonstandard country spellings → ISO 3166-1 alpha-2.
COUNTRY_OVERRIDES = {
    "Azores": "PT",
    "Bailiwick of Guernsey": "GG",
    "Bailiwick of Jersey": "JE",
    "Brunei": "BN",
    "Cape Verde": "CV",
    "Collectivity of Saint Martin": "MF",
    "Democratic Republic of the Congo": "CD",
    "Falkland Islands": "FK",
    "Guiné-Bissau": "GW",
    "Kosovo": "XK",
    "Macau": "MO",
    "Madeira": "PT",
    "Myanmar (Burma)": "MM",
    "New Calédonia": "NC",
    "Palestine": "PS",
    "Russia": "RU",
    "Saint Helena": "SH",
    "Saint-Pierre et Miquelon": "PM",
    "São Tomé and Príncipe": "ST",
    "Sint Maarten": "SX",
    "Tahiti": "PF",
    "The Bahamas": "BS",
    "The Gambia": "GM",
    "U.S. Virgin Islands": "VI",
    "Vatican City": "VA",
}


def _countries_path(bin_path: Path) -> Path:
    return bin_path.parent / "countries.json"


def _name_to_iso(bin_path: Path) -> dict[str, str]:
    """Country name → ISO2. Overrides + pycountry when installed +
    the reverse of the shipped countries.json (covers every name the
    current database already uses, so no dependency is required)."""
    mapping = dict(COUNTRY_OVERRIDES)
    try:
        existing = json.loads(_countries_path(bin_path).read_text())
        for code, name in existing.items():
            mapping.setdefault(name, code)
    except (OSError, ValueError):
        pass
    return mapping


def _iso2(name: str, mapping: dict[str, str]) -> str:
    code = mapping.get(name)
    if code:
        return code
    try:
        import pycountry
        code = pycountry.countries.lookup(name).alpha_2
    except Exception:
        log.warning("unknown country %r -> '??'", name)
        code = "??"
    mapping[name] = code
    return code


def fetch_places() -> list[dict]:
    resp = requests.get(PLACES_URL, timeout=60,
                        headers={"User-Agent": USER_AGENT,
                                 "Accept": "application/json"})
    resp.raise_for_status()
    return resp.json()["data"]["list"]


def encode(places: list[dict], mapping: dict[str, str]) -> bytes:
    out = [struct.pack("<4sHI6s", MAGIC, VERSION, len(places), b"\x00" * 6)]
    for p in places:
        lon, lat = p["geo"][0], p["geo"][1]     # geo is [LON, LAT]
        name = p.get("title", "Unknown")[:27].encode("utf-8", "replace")
        country = _iso2(p.get("country", "??"), mapping).encode("ascii")
        out.append(struct.pack(
            "<16shh28s4s",
            p["id"][:15].encode("utf-8").ljust(16, b"\x00"),
            max(-32767, min(32767, int(round(lat * 100)))),
            max(-32767, min(32767, int(round(lon * 100)))),
            name.ljust(28, b"\x00"),
            country.ljust(4, b"\x00"),
        ))
    return b"".join(out)


def refresh(bin_path: Path, places: list[dict],
            dry_run: bool = False) -> tuple[int, int]:
    """Validate + atomically install a new places.bin.
    Returns (added, removed) vs the previous file. Raises on any
    condition that should keep the old file in place."""
    old = PlacesDB.load(bin_path)
    old_ids = {p.id for p in old}

    if len(places) < MIN_COUNT:
        raise RuntimeError(f"only {len(places)} places — refusing")
    if len(places) < len(old_ids) * MIN_RATIO_OF_OLD:
        raise RuntimeError(
            f"new list ({len(places)}) shrank >10% vs current "
            f"({len(old_ids)}) — refusing")

    mapping = _name_to_iso(bin_path)
    blob = encode(places, mapping)

    tmp = bin_path.with_suffix(".bin.tmp")
    tmp.write_bytes(blob)
    fresh = PlacesDB.load(tmp)                 # must parse cleanly
    if len(fresh) != len(places):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("encoded file failed verification")

    new_ids = {p.id for p in fresh}
    added, removed = len(new_ids - old_ids), len(old_ids - new_ids)

    if dry_run:
        tmp.unlink(missing_ok=True)
        return added, removed

    shutil.copy2(bin_path, bin_path.with_suffix(".bin.bak"))
    os.replace(tmp, bin_path)

    # keep the ISO→name sidecar in step (new codes only, names stable)
    cpath = _countries_path(bin_path)
    try:
        current = json.loads(cpath.read_text())
    except (OSError, ValueError):
        current = {}
    for p in places:
        name = p.get("country", "")
        if name:
            current.setdefault(_iso2(name, mapping), name)
    cpath.write_text(json.dumps(dict(sorted(current.items())),
                                ensure_ascii=False, indent=1))
    return added, removed


def _wiim_is_playing() -> bool:
    """Best effort: True only if the configured speaker says 'play'."""
    try:
        from radiowall import config
        from radiowall.linkplay import LinkPlay
        ip = os.getenv("RADIOWALL_WIIM_IP", "").strip() \
            or str(config.get("wiim_ip") or "").strip()
        if not ip:
            return False
        status = LinkPlay(ip).get_status()
        return bool(status) and str(status.get("status")) == "play"
    except Exception:
        return False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--restart-if-idle", action="store_true",
                    help="try-restart radiowall.service unless music plays")
    ap.add_argument("--dry-run", action="store_true",
                    help="download + validate + report, install nothing")
    args = ap.parse_args()

    bin_path = places_db.default_path()
    log.info("refreshing %s", bin_path)
    places = fetch_places()
    added, removed = refresh(bin_path, places, dry_run=args.dry_run)
    log.info("%s: %d places (+%d new, -%d gone)%s",
             "dry-run" if args.dry_run else "installed",
             len(places), added, removed,
             "" if not args.dry_run else " — nothing written")

    if args.dry_run or not args.restart_if_idle:
        return 0
    if _wiim_is_playing():
        log.info("speaker is playing — skipping restart, file picked up "
                 "on next natural restart")
        return 0
    log.info("restarting radiowall to load the new file")
    subprocess.run(["systemctl", "try-restart", "radiowall.service"],
                   check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
