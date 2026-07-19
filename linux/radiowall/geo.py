"""Touch-frame position → geographic coordinates.

The IR frame reports normalized 0..1 coordinates (top-left origin). Until
the frame is physically mounted over the map print, we assume the whole
frame shows the whole equirectangular world map. Once mounted, the map
will occupy a sub-rectangle of the frame; `TouchCalibration` describes
that sub-rectangle in normalized frame coordinates and is loaded from a
JSON file (env RADIOWALL_TOUCH_CALIB) — a future calibration wizard just
writes that file, no code change.

Transform (equirectangular): lon = u*360 - 180, lat = 90 - v*180, where
(u, v) is the tap position normalized within the calibrated map area —
the same math the ESP32 used on its 1024×600 server space.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TouchCalibration:
    """Normalized frame-space rectangle that contains the map image."""
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 1.0
    y1: float = 1.0


def load_calibration() -> TouchCalibration:
    """Env-pointed JSON file wins; else the config store (written by the
    on-device calibration wizard); else identity."""
    path = os.getenv("RADIOWALL_TOUCH_CALIB", "").strip()
    if path:
        try:
            with open(path) as f:
                d = json.load(f)
            cal = TouchCalibration(x0=float(d["x0"]), y0=float(d["y0"]),
                                   x1=float(d["x1"]), y1=float(d["y1"]))
            log.info("touch calibration loaded from %s: %s", path, cal)
            return cal
        except (OSError, KeyError, ValueError) as e:
            log.warning("touch calibration %s unreadable (%s); using identity",
                        path, e)
            return TouchCalibration()

    from radiowall import config
    d = config.get("touch_calib")
    if isinstance(d, dict):
        try:
            cal = TouchCalibration(x0=float(d["x0"]), y0=float(d["y0"]),
                                   x1=float(d["x1"]), y1=float(d["y1"]))
            log.info("touch calibration from config store: %s", cal)
            return cal
        except (KeyError, ValueError, TypeError) as e:
            log.warning("config touch_calib invalid (%s); using identity", e)
    return TouchCalibration()


def tap_to_latlon(x: float, y: float,
                  cal: TouchCalibration | None = None) -> tuple[float, float]:
    cal = cal or TouchCalibration()
    u = (x - cal.x0) / (cal.x1 - cal.x0)
    v = (y - cal.y0) / (cal.y1 - cal.y0)
    u = min(1.0, max(0.0, u))
    v = min(1.0, max(0.0, v))
    lon = u * 360.0 - 180.0
    lat = 90.0 - v * 180.0
    return lat, lon
