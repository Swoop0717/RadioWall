# CLAUDE.md — RadioWall Project Context

> Technical reference for AI assistants working on this codebase.

## Project Overview

RadioWall is an interactive physical world map that plays local radio stations
when you touch a location. Touch Vienna → Austrian radio. Touch Tokyo →
Japanese radio.

**Vision**: a physical paper/cloth map sits behind an invisible IR touch
frame. No screen on the map — a small 256×64 OLED shows "now playing", one
rotary knob drives everything else.

**Data flow**: Touch → nearest city in a local places DB → fetch stations from
Radio.garden → play. Two output paths:
- **WiFi (WiiM/LinkPlay)**: the speaker streams the URL itself; the board only
  coordinates (HTTPS `httpapi.asp` commands).
- **Bluetooth**: the board decodes with ffmpeg and pushes PCM to the speaker
  via bluealsa (A2DP source).

## Production Setup

Everything lives in [linux/](linux/) — Python 3.10, runs as a systemd service
(`radiowall.service`, root) on an **Orange Pi Zero 3W (Allwinner A733)** at
`192.168.0.5` (user `orangepi`, key SSH, passwordless sudo). Display:
3.12" 256×64 **SSD1322** OLED (`RADIOWALL_DISPLAY=ssd1322`). Inputs: EC11
rotary encoder on GPIO, 55" IR touch frame as USB HID (`/dev/input/eventN`).

- **Deploy**: rsync `linux/` to `orangepi@192.168.0.5:RadioWall/linux/`,
  `sudo systemctl restart radiowall` (check whether music is playing first —
  a restart silences it).
- **Config store**: `/var/lib/radiowall/config.json` (root service;
  `StateDirectory=radiowall`), written by the on-device setup menu. Env vars
  override config (`/etc/radiowall.env`). History/favorites in
  `/var/lib/radiowall/history.json`.
- **Timers/units**: `radiowall-places.timer` (weekly places.bin refresh,
  Mon 04:30), `bluealsa.service` (`-p a2dp-source`; Jammy ships no unit),
  `bluetooth.service`.
- **The A733 boots ONLY the vendor Orange Pi Ubuntu Jammy image** (no
  DietPi/Armbian). Serial console: header pin 8 = board TX, pin 10 = RX,
  115200 8N1. PWRIN Type-C has no PD — plain 5 V/3 A via A→C cable.
- Old dev rig (Pi 3 B+ / DietPi, ST7789 240×135 HAT) still works; board
  profiles auto-detect (`radiowall/hw/board.py`).

## UI / Gesture Grammar ("the longer you hold, the more drastic")

- **Tap** = next station; on the idle screen = resume last played
- **Double-tap** = cycle status screen ↔ 8 visualizers
- **Triple-tap** = star/unstar the current station (records it immediately)
- **Hold ~0.8 s** = menu, music keeps playing: Sleep timer · History ·
  Favorites · Setup (Speaker WiFi/BT, WiFi, Touch calibration, Info)
- **Keep holding ~3 s** = stop everything
- Rotate = volume (playback) / navigate (menu) / oven-dial (sleep timer:
  10 min per detent, 30 min when spun fast)
- In lists: press = select/play, double-press = star / group-toggle / forget
  (context hints always shown in the title bar)

## Key Subsystems (linux/radiowall/)

| Module | Role |
|---|---|
| `main.py` | render loop ~50 Hz, input dispatch, smart redraw (skips repainting static screens) |
| `radio.py` | RadioWorker: command queue, session/city-hop, sleep timer, history recording (>30 s), silent-station skip (~20 s, decoder RMS), dead-tap auto-hop (≤5 empty cities), output swap with playback transfer |
| `state.py` | thread-safe Snapshot for the render loop |
| `linkplay.py` | WiiM HTTPS client (play/vol/sleep/multiroom/switchmode/position) |
| `btplayer.py` | BT output: ffmpeg → bluealsa A2DP; exclusive PCM, generation-guarded respawns |
| `btaudio.py` | bluetoothctl scan/pair/connect/forget |
| `discovery.py` | SSDP discovery of LinkPlay speakers |
| `wifi.py` | nmcli scan/connect (on-device WiFi setup) |
| `config.py` / `history.py` | persisted config + history/favorites |
| `radio_garden.py` / `places_db.py` | station API + binary places DB |
| `audio/decoder.py` | ffmpeg tap → FFT bands (16, per-band dB AGC), waveform/RMS, ICY titles, consumption-clock sync to WiiM curpos |
| `display/screens.py` | status screen (font-metric layout, cached scroll strips, junk-ICY filter) |
| `display/visualizer.py` | vfd/bars/mirror/radial/wave/scope/waterfall/vu |
| `display/setup_ui.py` | the whole menu system |
| `display/pixel_shift.py` | OLED burn-in orbit (1 px / 4 min) |
| `tools/refresh_places.py` | weekly places.bin refresh (validates before swap, restarts only when idle) |

Tests: `linux/tests/` (~127, pure Python — no hardware needed). Emulator:
`RADIOWALL_EMULATE=1 python -m radiowall`.

## Critical Behavioral Rules (learned the hard way)

- **Never interrupt playing music for housekeeping** — refreshers/updaters
  check the speaker state and defer restarts.
- **The bluealsa A2DP PCM is exclusive**: exactly one ffmpeg may hold it;
  every spawn commits under a generation lock, and output swaps `close()` the
  old BtPlayer.
- **WiiM as BT sink**: WiiM never auto-switches input — send
  `setPlayerCmd:switchmode:bluetooth`; its device volume is a hidden second
  stage behind the A2DP link volume (raise to ≥45 if very low).
- **Grouped LinkPlay slaves vanish from SSDP** — merge the master's
  `multiroom:getSlaveList` into discovery results.
- **Layout from font metrics, never fixed pixel fractions** (a 12 px font is
  15 px tall; 26%-of-64px separator lines cut descenders).
- Radio.garden's place list churns ~3%/week; stale-removed places cause
  dead taps → weekly refresh + auto-hop.
- ffmpeg 4.4 (Jammy) never logs ICY titles on stderr — the dedicated
  metadata reader connection exists for that (closes immediately when the
  station has no `icy-metaint`).

## Radio.garden API

Unofficial, no auth:

```
GET http://radio.garden/api/ara/content/places
# response.data.list[]: { id, title, country, geo: [lon, lat], size }
# NOTE: geo is [LON, LAT], not [lat, lon]

GET http://radio.garden/api/ara/content/page/{place_id}/channels
# response.data.content[0].items[]: { page: { url: "/listen/{slug}/{id}", title } }

GET http://radio.garden/api/ara/content/listen/{station_id}/channel.mp3
# 302 redirect to the real stream URL
```

Their city↔station mapping is editorially curated — there is no open upstream
to replace it (radio-browser.info was evaluated 2026-07-18: only ~20-30% of
stations geo-tagged, remote regions far worse).

## LinkPlay API (WiiM)

Base: `https://<wiim-ip>/httpapi.asp?command=<cmd>` (HTTPS 443, self-signed
cert — `verify=False`; port 80 refused).

| Command | Description |
|---|---|
| `getPlayerStatus` | JSON status; `vol` may be quoted; `curpos` ms drives visualizer sync; `mode` 41=bluetooth input |
| `setPlayerCmd:play:<url>` | Play URL (partial percent-encoding: only `: / ? & =` — firmware quirk, don't "fix") |
| `setPlayerCmd:pause/resume/stop` | Transport |
| `setPlayerCmd:vol:<0-100>` | Volume |
| `setSleepTimer:<seconds>` | Native auto-shutoff (0 cancels) |
| `setPlayerCmd:switchmode:<wifi\|bluetooth\|...>` | Input select |
| `multiroom:getSlaveList` / `SlaveKickout:<ip>` / `Ungroup` | Group mgmt (on master) |
| `ConnectMasterAp:JoinGroupMaster:eth<ip>:wifi0.0.0.0` | Join a group (sent to the SLAVE) |
| `getStatusEx` | Extended device info |

References: [WiiM HTTP API pdf](https://www.wiimhome.com/pdf/HTTP%20API%20for%20WiiM%20Products.pdf),
[AndersFluur/LinkPlayApi](https://github.com/AndersFluur/LinkPlayApi).

## places.bin Format

Compiled by `tools/compile_places.py`, refreshed on-device by
`radiowall/tools/refresh_places.py` (same RGPL format):

```
Header (16 B): magic "RGPL", uint16 version, uint32 count, 6 B reserved
Place  (52 B): char[16] id, int16 lat*100, int16 lon*100, char[28] name, char[4] country
```

`linux/data/countries.json` maps the 2-letter codes back to display names.

## Repo Layout

```
RadioWall/
├── linux/              # the product: Python app, tests, systemd units, data
├── tools/              # places compiler, tiled map PDF generator
├── CLAUDE.md
└── readme.md
```

The original ESP32 firmware (two working prototypes), its map-bitmap tooling
and the early design docs live on the **`legacy/esp32`** branch.

## Roadmap (agreed 2026-07-18)

1. Push/PR flow on GitHub (`Swoop0717/RadioWall`), releases with version tags
2. OTA updater: GitHub releases API, stable/beta channels, versioned dirs +
   `current` symlink, rollback, never-while-playing
3. `linux/setup.sh` provisioning script → generalized flashable golden image
4. Physical build: map print (tools/generate_tiled_map.py), frame mounting,
   on-device touch calibration
