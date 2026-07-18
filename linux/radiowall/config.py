"""Persistent device configuration — the anti-hardcoding layer.

One JSON file (default ~/.config/radiowall/config.json, override with
RADIOWALL_CONFIG) written atomically by the on-device setup UI and read
everywhere a value used to be hardcoded: WiiM address, touch
calibration, etc.

Precedence everywhere: env var > config file > built-in default. Env
vars stay authoritative so dev setups and /etc/radiowall.env keep
working unchanged; the config file is what the setup UI edits.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, Any] | None = None


def path() -> Path:
    env = os.getenv("RADIOWALL_CONFIG", "").strip()
    if env:
        return Path(env)
    # The production service runs as root — its state belongs in
    # /var/lib (the systemd unit sets StateDirectory=radiowall), not
    # in /root/.config where nobody would look for it.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return Path("/var/lib/radiowall/config.json")
    return Path.home() / ".config" / "radiowall" / "config.json"


def _load() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(path()) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("config root is not an object")
        _cache = data
        log.info("config loaded from %s (%d keys)", path(), len(data))
    except FileNotFoundError:
        _cache = {}
    except (OSError, ValueError) as e:
        log.warning("config %s unreadable (%s); starting empty", path(), e)
        _cache = {}
    return _cache


def get(key: str, default: Any = None) -> Any:
    with _lock:
        return _load().get(key, default)


def set(key: str, value: Any) -> None:
    """Set and persist immediately (atomic tmp+rename)."""
    with _lock:
        data = _load()
        data[key] = value
        p = path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, p)
            log.info("config saved: %s", key)
        except OSError as e:
            log.error("config save failed (%s): %s", p, e)


def reset_cache_for_tests() -> None:
    global _cache
    with _lock:
        _cache = None
