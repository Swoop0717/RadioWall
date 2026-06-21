# RadioWall Linux Port — Plan

Current hardware: **Raspberry Pi 3 B+ (1 GB), DietPi (Debian Trixie)**.
Original target: Orange Pi Zero 3W (Allwinner H618) — **parked, won't boot**
(awaiting a USB power tester + CP2102 serial console to diagnose). The Python
code is board-agnostic; moving back is mostly SPI bus/device + GPIO pinouts.
Dev hardware: laptop with native Python (pygame emulator).
Speaker: WiiM Amp Pro at `192.168.0.33`.
Display: target is a 3.12" SSD1322 256×64 OLED over SPI; current dev panel is a
1.14" 240×135 ST7789 TFT (driver done, `RADIOWALL_DISPLAY=st7789`).
Touch: 55" IR frame via USB HID (shows up as `/dev/input/eventN`).
Inputs: EC11 rotary encoders + buttons (incl. 2 on the ST7789 TFT, GPIO 23/24).

## Goals & Non-Goals

**Goals**
- Feature parity with the ESP32 standalone firmware (touch → nearest city → play on WiiM).
- Clean dev loop: emulator-based UI development on Windows, no Pi required until integration.
- Boringly reliable at runtime: runs under systemd, restarts on crash, logs everything.
- Observability: live log mirror, a status endpoint, optional UDP broadcast.

**Non-Goals (v1)**
- No audio processing on the Pi — WiiM handles the stream, we just coordinate.
- No web UI for end users. A status endpoint for debugging, not a dashboard.
- No multiple-simultaneous-speaker orchestration beyond LinkPlay multiroom.

## Stack Decisions

| Decision | Choice | Reason |
|---|---|---|
| Language | Python 3.11 | Best SBC hardware-library ecosystem; existing server/ code reusable |
| Deps manager | `uv` | Fast, lockfile, modern |
| OS | DietPi | ~80 MB idle RAM; opinionated for headless SBCs |
| Config | YAML | Human-editable WiiM IP, favorites, thresholds |
| Concurrency | Single-threaded poll loop | Event rate ~10–60 Hz; no async complexity needed |
| OLED driver | `luma.oled` | Mature SSD1322 support + pygame emulator |
| Touch input | `python-evdev` | Standard for Linux input |
| GPIO | `gpiod` | Modern kernel ABI, replaces deprecated sysfs |
| Logging | stdlib `logging` | Three sinks: stderr (journald), UDP, optional file |
| Status API | FastAPI | Small, fast, async — worth the dep for auto-docs |
| Tests | pytest | Unit tests for state machine + clients |

## Package Structure

```
linux/
├── PLAN.md                ← this file
├── README.md              ← install/usage (post-scaffold)
├── pyproject.toml         ← uv-managed deps
├── config.example.yaml
├── systemd/
│   └── radiowall.service  ← production unit file
├── radiowall/
│   ├── __init__.py
│   ├── main.py            ← entry point, main loop
│   ├── config.py          ← YAML loader, validation
│   ├── state.py           ← app state machine
│   ├── radio_garden.py    ← port of server/radio_garden.py
│   ├── linkplay.py        ← HTTPS client for WiiM
│   ├── places_db.py       ← reader for places.bin
│   ├── logging_setup.py   ← configure handlers
│   ├── status_api.py      ← FastAPI status endpoint + UDP broadcaster
│   ├── display/
│   │   ├── __init__.py    ← Display protocol (Protocol class)
│   │   ├── ssd1322.py     ← real luma.oled SSD1322
│   │   └── emulator.py    ← luma.oled pygame emulator
│   └── input/
│       ├── __init__.py    ← Event protocol, event queue
│       ├── evdev_touch.py ← /dev/input/eventN reader for 55" IR frame
│       ├── gpiod_buttons.py ← rotary + buttons
│       └── keyboard_mock.py ← dev-time keyboard input
└── tests/
    ├── test_state.py
    ├── test_places_db.py
    └── test_linkplay.py    (mocks httpx)
```

## Build Order

Each step ends with something demonstrable.

1. **Scaffolding** — `pyproject.toml`, package skeleton, `python -m radiowall --help` works.
2. **LinkPlay client + CLI** — `python -m radiowall.linkplay play <url>` against the real WiiM. Proves the network side end-to-end.
3. **Radio.garden client + CLI** — `python -m radiowall.radio_garden nearest <lat> <lon>`. Proves the API side.
4. **Places DB + end-to-end CLI** — `python -m radiowall.play 48.21 16.37` → finds Vienna → fetches stations → sends to WiiM. **First full vertical slice, zero UI.**
5. **Logging + config** — wire up stdlib `logging`, YAML config loader, module-level loggers.
6. **Status API skeleton** — `GET /status`, `GET /health` running alongside. Open `localhost:8080/status` in the browser.
7. **OLED UI via luma emulator** — splash, now-playing, menu screens. Pygame window on Windows.
8. **Keyboard-mocked inputs** — arrow keys drive the menu; full app loop runs on the laptop.
9. **State machine hardening** — error states, reconnect logic, station exhaustion + hopping.
10. **Pi-side drivers** (when board arrives) — real evdev touch, real gpiod encoders/buttons. Slot in behind the same protocols.
11. **systemd unit + deployment** — copy `.service`, enable, autostart.
12. **Thermals + suspend test** — measure, decide on standby strategy.

## Dev Workflow — Windows → Pi

### Now, on Windows

```bash
cd linux
uv venv && .venv\Scripts\activate
uv pip install -e .[dev]
RADIOWALL_EMULATE=1 python -m radiowall
```

A pygame window pops up showing the OLED. Arrow keys = rotary encoder. Enter = push. Numbers = buttons. Network calls hit the real WiiM on the LAN.

### When the Pi arrives

First boot (from your laptop, no monitor):
1. Flash DietPi to SD, edit `dietpi-wifi.txt` and `dietpi.txt` on boot partition with WiFi + preferred user.
2. Boot — self-installs in ~5 min.
3. Find on LAN: `ping radiowall.local` (mDNS) or check router DHCP.
4. `ssh dietpi@radiowall.local`, change password.

Deploy workflow:
```bash
# On the Pi (first time only)
git clone <repo>
cd RadioWall/linux
uv venv && uv pip install -e .
cp config.example.yaml config.yaml   # edit WiiM IP, etc.

# Every subsequent deploy
git pull
systemctl restart radiowall
```

**VSCode Remote-SSH** is the intended primary tool:
- Remote-SSH extension connects to `dietpi@radiowall.local`
- VSCode opens the repo *on the Pi* — integrated terminal, file editor, debugger all operate remotely
- Claude Code / AI tooling stays on the laptop but edits Pi files transparently
- No monitor/keyboard plugged into the Pi, ever

## Logging Architecture

### Goals

- **Default**: stdout → journald, queryable via `journalctl`, automatic rotation.
- **Live tail from the laptop** without SSH: optional UDP broadcast to a laptop listener.
- **Module-level filtering**: noisy components (touch event stream) silenceable independently.
- **Config-driven**: log level, UDP on/off, file sink on/off — all in `config.yaml`.

### Configuration (single call at startup)

```python
# radiowall/logging_setup.py
import logging
import logging.handlers

def setup_logging(cfg):
    root = logging.getLogger()
    root.setLevel(cfg["level"])  # DEBUG/INFO/WARNING/ERROR

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # 1. stderr → systemd journald (always on)
    stderr = logging.StreamHandler()
    stderr.setFormatter(fmt)
    root.addHandler(stderr)

    # 2. UDP broadcast (opt-in)
    if cfg.get("udp_host"):
        udp = logging.handlers.DatagramHandler(cfg["udp_host"], cfg.get("udp_port", 9999))
        udp.setFormatter(fmt)
        root.addHandler(udp)

    # 3. Rotating file (opt-in)
    if cfg.get("file_path"):
        f = logging.handlers.RotatingFileHandler(
            cfg["file_path"], maxBytes=1_000_000, backupCount=3
        )
        f.setFormatter(fmt)
        root.addHandler(f)

    # 4. Per-module level overrides (e.g. mute verbose touch events)
    for name, level in cfg.get("module_levels", {}).items():
        logging.getLogger(name).setLevel(level)
```

### `config.yaml` logging section

```yaml
logging:
  level: INFO
  udp_host: 192.168.0.10   # laptop IP, or null to disable
  udp_port: 9999
  file_path: null          # or /var/log/radiowall/app.log
  module_levels:
    radiowall.input.touch: WARNING   # only noise when weird
    radiowall.linkplay: DEBUG
```

### Module-level loggers

Each module does:
```python
import logging
log = logging.getLogger(__name__)   # e.g. "radiowall.linkplay"
```

### Log levels convention

| Level | Use for |
|---|---|
| DEBUG | Every touch/GPIO event, every HTTP request+response body |
| INFO | State transitions, station plays/stops, WiFi connect, config loaded |
| WARNING | Stream fail, WiiM timeout, station list empty |
| ERROR | Config invalid, places.bin missing, OLED SPI init failed, unhandled exception |
| CRITICAL | (unused — if we're here, we're dead anyway) |

Start in DEBUG during dev, flip to INFO in production.

### Tailing logs

**On the Pi:**
```bash
journalctl -u radiowall -f                 # live tail
journalctl -u radiowall --since "1h ago"   # recent history
journalctl -u radiowall -p warning         # warnings and up
journalctl -u radiowall | grep linkplay    # filter by module
```

**On the laptop (UDP listener):**
```bash
nc -ul 9999
# OR a nicer Python listener with color coding
python -m radiowall.tools.udp_log_listen
```

The UDP listener is basically `while True: line = sock.recv(); print(line)`. We can add ANSI colors by level.

## Status API + UDP Broadcast

Two separate channels for the same underlying state:

1. **HTTP status API** — pull-based, query on demand.
2. **UDP state broadcast** — push-based, LAN devices passively listen.

### HTTP API (FastAPI on port 8080)

```
GET /health            → 200 {"ok": true}
GET /status            → full state JSON
GET /metrics           → prometheus text format (optional)
POST /command          → {"cmd": "stop" | "next" | "play" | "volume", "value": 50}
```

Example `/status` payload:
```json
{
  "playing": true,
  "station": "Radio Wien",
  "city": "Vienna",
  "country": "AT",
  "station_index": 2,
  "station_total": 5,
  "lat": 48.21,
  "lon": 16.37,
  "volume": 45,
  "uptime_s": 83421,
  "wifi_rssi_dbm": -52,
  "cpu_temp_c": 58.2,
  "mem_used_mb": 78,
  "wiim_reachable": true
}
```

Runs in a thread alongside the main loop (FastAPI via uvicorn, `thread=True`).

### UDP status broadcast

Every N seconds (default: 5), broadcast the same `/status` payload as JSON to port 9998:

```python
import socket, json, time
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

def broadcast(state: dict):
    sock.sendto(json.dumps(state).encode(), ("255.255.255.255", 9998))
```

Anyone on the LAN can passively listen:
```bash
nc -ul 9998                    # raw
python -m radiowall.tools.udp_status_listen   # pretty-printed
```

Use cases:
- Home Assistant auto-discovery via MQTT bridge (future).
- A second screen / desk clock showing what's playing.
- Debugging from the couch without SSH.

### Config

```yaml
status_api:
  enabled: true
  bind: 0.0.0.0
  port: 8080

status_broadcast:
  enabled: true
  port: 9998
  interval_s: 5
```

## Testing

**Unit tests** (pytest, run on every commit):
- `state.py` — state transitions, invalid transitions rejected
- `places_db.py` — parse fixture, nearest-neighbor correctness
- `linkplay.py` — HTTP calls mocked with `responses` or `httpx-mock`
- `radio_garden.py` — responses fixture with real API payloads captured once

**Not unit tested** (smoke-tested manually):
- OLED rendering (eyeball the emulator)
- evdev touch (hardware in the loop)
- gpiod inputs (hardware in the loop)

**Integration smoke tests** (manual, on the Pi):
- `python -m radiowall.play 48.21 16.37` → music plays on WiiM → stop
- Cycle inputs, verify state transitions in `journalctl`
- Leave running 24h, check uptime + memory in `/status`

## systemd Service

```ini
# systemd/radiowall.service
[Unit]
Description=RadioWall
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=dietpi
WorkingDirectory=/home/dietpi/RadioWall/linux
ExecStart=/home/dietpi/RadioWall/linux/.venv/bin/python -m radiowall
Restart=on-failure
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Install:
```bash
sudo cp systemd/radiowall.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now radiowall
```

## Open Questions / Decisions Pending

- **Suspend vs always-on**: confirm after the board arrives and we measure. Default to always-on fake-standby; add real suspend later if reliable.
- **Encoder input decoding**: kernel `rotary-encoder` overlay (clean evdev events) vs userspace `gpiod` polling? Prefer the overlay if we can configure it via DTBO.
- **OLED layout**: single "now playing" screen vs multi-screen menu navigated by encoder. Sketch before implementing.
- **Persistence**: favorites + history — JSON files in `~/.radiowall/`? SQLite? JSON is fine for v1.
- **Remote control via `/command`**: security — LAN-only via `bind: 127.0.0.1` initially, or accept anyone on LAN? Probably LAN-only is fine for a home frame.
