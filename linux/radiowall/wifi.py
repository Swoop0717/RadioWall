"""WiFi via NetworkManager (nmcli) — scan, status, connect.

The Orange Pi Ubuntu image runs NetworkManager, so joining a network
is one nmcli call and the credentials persist as an NM connection
profile; nothing for us to store. All functions shell out through a
`run` callable injected for tests.

nmcli -t output escapes ':' inside fields as '\\:' — `_split_t`
handles that (SSIDs may contain colons).
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

_NMCLI_TIMEOUT_S = 45          # connect can take a while (DHCP)


@dataclass(frozen=True)
class Network:
    ssid: str
    signal: int                # 0-100
    secured: bool
    known: bool = False        # NM already has a profile for it


def _run(args: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=_NMCLI_TIMEOUT_S)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "nmcli not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "nmcli timed out"


def _split_t(line: str) -> list[str]:
    """Split one `nmcli -t` line on unescaped ':' and unescape fields."""
    fields, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    fields.append("".join(cur))
    return fields


def known_ssids(run=_run) -> set[str]:
    rc, out, _err = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection",
                         "show"])
    if rc != 0:
        return set()
    names = set()
    for line in out.splitlines():
        f = _split_t(line)
        if len(f) >= 2 and f[1] == "802-11-wireless":
            names.add(f[0])
    return names


def scan(run=_run) -> list[Network]:
    """Visible networks, strongest first, deduped by SSID."""
    rc, out, err = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY",
                        "device", "wifi", "list", "--rescan", "yes"])
    if rc != 0:
        log.warning("wifi scan failed: %s", err.strip() or rc)
        return []
    known = known_ssids(run)
    best: dict[str, Network] = {}
    for line in out.splitlines():
        f = _split_t(line)
        if len(f) < 3 or not f[0]:
            continue                        # hidden SSID
        try:
            signal = int(f[1])
        except ValueError:
            signal = 0
        n = Network(ssid=f[0], signal=signal,
                    secured=f[2].strip() not in ("", "--"),
                    known=f[0] in known)
        if n.ssid not in best or n.signal > best[n.ssid].signal:
            best[n.ssid] = n
    return sorted(best.values(), key=lambda n: -n.signal)


def status(run=_run) -> tuple[str, str]:
    """(connected SSID or '', IPv4 address or '')."""
    ssid = ""
    rc, out, _ = run(["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"])
    if rc == 0:
        for line in out.splitlines():
            f = _split_t(line)
            if len(f) >= 2 and f[0] == "yes":
                ssid = f[1]
                break
    ip = ""
    rc, out, _ = run(["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show",
                      "wlan0"])
    if rc == 0:
        for line in out.splitlines():
            f = _split_t(line)
            if len(f) >= 2 and f[1]:
                ip = f[1].split("/")[0]
                break
    return ssid, ip


def connect(ssid: str, password: str | None, run=_run) -> tuple[bool, str]:
    """Join a network. Empty/None password → open network or an SSID
    NetworkManager already knows (its stored profile is used)."""
    if not password and ssid in known_ssids(run):
        args = ["nmcli", "connection", "up", "id", ssid]
    else:
        args = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            args += ["password", password]
    rc, out, err = run(args)
    ok = rc == 0
    msg = (out if ok else err).strip().splitlines()
    detail = msg[0] if msg else ("connected" if ok else f"failed (rc={rc})")
    log.info("wifi connect %s: %s", ssid, detail)
    return ok, detail
