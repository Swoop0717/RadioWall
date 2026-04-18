"""Centralised logging configuration.

One call to setup() at startup wires up:
  - stderr handler (always; journald captures this under systemd)
  - UDP handler (opt-in via RADIOWALL_LOG_UDP=host:port)
  - Per-module level overrides (RADIOWALL_LOG_MODULES="mod=LEVEL,mod=LEVEL")

Every module does:

    import logging
    log = logging.getLogger(__name__)

and then `log.info("...")` — no handler plumbing in the module itself.

Env vars (promoted to YAML later, per PLAN.md Step 5):
  RADIOWALL_LOG_LEVEL      DEBUG/INFO/WARNING/ERROR (default INFO)
  RADIOWALL_LOG_UDP        "host:port" (default unset → no UDP)
  RADIOWALL_LOG_MODULES    e.g. "radiowall.input=WARNING,urllib3=WARNING"
"""

from __future__ import annotations

import logging
import logging.handlers
import os

_FORMAT = "%(asctime)s %(levelname)-5s %(name)s: %(message)s"
_DATEFMT = "%H:%M:%S"


class _StringDatagramHandler(logging.handlers.DatagramHandler):
    """Send the formatted log line as UTF-8 bytes instead of a pickled record.

    The stdlib DatagramHandler emits pickled LogRecords which the
    receiver has to unpickle (and which is unsafe to eval from the
    network). We want the listener side to be a four-line `nc`-equivalent.
    """

    def makePickle(self, record: logging.LogRecord) -> bytes:
        return self.format(record).encode("utf-8", errors="replace")


def setup() -> None:
    """Configure the root logger from RADIOWALL_LOG_* env vars. Idempotent."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    level = os.getenv("RADIOWALL_LOG_LEVEL", "INFO").upper()
    root.setLevel(level)

    fmt = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    stderr = logging.StreamHandler()
    stderr.setFormatter(fmt)
    root.addHandler(stderr)

    udp_target = os.getenv("RADIOWALL_LOG_UDP", "").strip()
    if udp_target:
        host, _, port = udp_target.partition(":")
        udp = _StringDatagramHandler(host, int(port) if port else 9999)
        udp.setFormatter(fmt)
        root.addHandler(udp)

    modules = os.getenv("RADIOWALL_LOG_MODULES", "").strip()
    if modules:
        for entry in modules.split(","):
            name, _, lvl = entry.strip().partition("=")
            if name and lvl:
                logging.getLogger(name).setLevel(lvl.upper())

    log = logging.getLogger(__name__)
    log.debug("logging configured: level=%s udp=%s modules=%s",
              level, udp_target or "off", modules or "none")
