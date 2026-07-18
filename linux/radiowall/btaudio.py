"""Bluetooth speaker management via bluetoothctl (BlueZ 5).

Scan, pair, connect, forget — all through bluetoothctl's
non-interactive subcommands, with an injectable runner for tests.
Audio output itself goes through bluealsa (see btplayer).

Devices whose name is just their MAC with dashes (BLE gadgets that
never answered a name request) are filtered out of scan results —
they're not speakers anyone could recognize anyway.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

SCAN_S = 8
_DEVICE_RE = re.compile(r"Device ((?:[0-9A-F]{2}:){5}[0-9A-F]{2}) (.+)",
                        re.IGNORECASE)


@dataclass(frozen=True)
class BtDevice:
    mac: str
    name: str
    paired: bool = False
    connected: bool = False


def _run(args: list[str], timeout: float = 30) -> tuple[int, str, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "bluetoothctl not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "bluetoothctl timed out"


def _parse_devices(out: str) -> dict[str, str]:
    devices: dict[str, str] = {}
    for line in out.splitlines():
        m = _DEVICE_RE.search(line)
        if not m:
            continue
        mac, name = m.group(1).upper(), m.group(2).strip()
        if name.replace("-", ":").upper() == mac:
            continue                     # nameless BLE noise
        devices[mac] = name
    return devices


def paired_macs(run=_run) -> dict[str, str]:
    rc, out, _ = run(["bluetoothctl", "paired-devices"])
    return _parse_devices(out) if rc == 0 else {}


def is_connected(mac: str, run=_run) -> bool:
    rc, out, _ = run(["bluetoothctl", "info", mac])
    return rc == 0 and "Connected: yes" in out


def scan(run=_run) -> list[BtDevice]:
    """Discover nearby named devices; paired ones first."""
    run(["bluetoothctl", "--timeout", str(SCAN_S), "scan", "on"],
        timeout=SCAN_S + 10)
    rc, out, _ = run(["bluetoothctl", "devices"])
    found = _parse_devices(out) if rc == 0 else {}
    paired = paired_macs(run)
    found.update(paired)                 # paired always listed, even if asleep
    devices = [
        BtDevice(mac=mac, name=name, paired=mac in paired,
                 connected=mac in paired and is_connected(mac, run))
        for mac, name in found.items()
    ]
    devices.sort(key=lambda d: (not d.connected, not d.paired, d.name.lower()))
    return devices


def connect(mac: str, run=_run) -> tuple[bool, str]:
    """Pair (idempotent), trust (enables auto-reconnect), connect."""
    run(["bluetoothctl", "pair", mac], timeout=45)     # ok if already paired
    run(["bluetoothctl", "trust", mac])
    rc, out, err = run(["bluetoothctl", "connect", mac], timeout=45)
    ok = rc == 0 and "Connection successful" in out
    msg = "connected" if ok else (err.strip() or out.strip() or "failed")
    log.info("bt connect %s: %s", mac, msg.splitlines()[-1] if msg else "?")
    return ok, msg


def disconnect(mac: str, run=_run) -> bool:
    rc, _out, _err = run(["bluetoothctl", "disconnect", mac])
    return rc == 0


def forget(mac: str, run=_run) -> bool:
    run(["bluetoothctl", "disconnect", mac])
    rc, _out, _err = run(["bluetoothctl", "remove", mac])
    return rc == 0
