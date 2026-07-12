# CLAUDE.md — RadioWall Project Context

> Technical reference for AI assistants working on this codebase.

## Project Overview

RadioWall is an interactive physical world map that plays local radio stations when you touch a location. Touch Vienna → Austrian radio. Touch Tokyo → Japanese radio.

**Vision**: a physical paper/cloth map sits behind invisible capacitive touch. No screen on the map — a small status display (or none at all) shows "Now Playing".

**Data flow**: Touch → compute board finds nearest city in a local places DB → fetches stations from Radio.garden → sends stream URL to a WiiM speaker via LinkPlay HTTPS → WiiM streams directly from the internet. The compute board never handles audio.

## Two Tracks

### [esp32/](esp32/) — ESP32 firmware (feature complete, reference)

Working prototypes on ESP32-S3. Tagged `v1.0-prototype1` for P1. This track is **no longer active development** but kept as working reference firmware and as the source of truth for the hardware + LinkPlay/Radio.garden behavior.

- **P1** (`env:t-display-s3-long`): LILYGO T-Display-S3-Long. Built-in 3.4" AMOLED + I2C touch. Full standalone firmware: map UI, favorites, history, settings, volume, sleep timer, multiroom, zoom.
- **P2** (`env:usb-touch`): ESP32-S3 + 55" IR touch frame over USB Host. Serial replaced by WiFi UDP logging (port 9999). Control zone: `server_y > 550` = play/pause.

### [linux/](linux/) — Linux SBC port (active)

Porting the standalone logic to Python on real Linux userspace — easier UI, faster iteration, IR frame as `/dev/input/eventN`, no LittleFS/PSRAM gymnastics.

**Running now** on the final target: an **Orange Pi Zero 3W (A733)** at `192.168.0.5` (user `orangepi`, key SSH, passwordless sudo) driving the 3.12" 256×64 **SSD1322** OLED (`RADIOWALL_DISPLAY=ssd1322`): VFD-style "now playing" mockup + four audio-reactive visualizers, HTTP proxy re-serving the stream to the WiiM (`:8000`) while ffmpeg→FFT feeds the visualizer. Board profiles (`radiowall/hw/board.py`) auto-detect Pi vs Orange Pi; GPIO on non-Pi goes through a gpiod-v2 RPi.GPIO shim (`radiowall/hw/gpio_compat.py`). The old dev rig — **Raspberry Pi 3 B+ / DietPi** with the 1.14" ST7789 HAT, systemd service, `/etc/radiowall.env`, at `192.168.0.102` — still works unchanged as fallback. Mode cycling was HAT-button-only; wiring the EC11 encoder into `main.py` is the next step.

**Not yet ported:** the actual radio logic (LinkPlay, Radio.garden, `places.bin` lookup, touch→city→play state machine) — held until the final hardware (SSD1322 256×64 OLED + EC11 encoders + 55" IR frame) is wired and tested. The screen is still a hardcoded mockup.

**Original target was the Orange Pi Zero 3W (Allwinner A733** — not H618 as earlier notes said**)** — the "won't boot" mystery was resolved 2026-07-12: the board boots the official Orange Pi Ubuntu Jammy image fine; it had merely looked dead (no WiFi configured, no display attached). Serial console: 40-pin header pin 8 = board TX, pin 10 = board RX, pin 6 = GND, 115200 8N1, 3.3 V. PWRIN Type-C has **no PD negotiation** — plain 5 V/3 A supply via USB-A→C cable only. DietPi/Armbian do **not** support the A733 — official Orange Pi images only. Code is board-agnostic. See `linux/README.md` for the full setup + lessons (Ethernet-first install, `python3-rpi-lgpio` GPIO backend, SPI at `/boot/firmware/config.txt`).

## How It Works (both tracks)

1. Touch → pixel coords → (lat, lon)
2. Find nearest city in places DB (~12,500 cities, packed binary from `tools/compile_places.py`)
3. Fetch station list from Radio.garden (`/api/ara/content/page/{place_id}/channels`)
4. Resolve stream URL (follow first redirect on `/listen/{id}/channel.mp3`)
5. `GET https://<wiim>/httpapi.asp?command=setPlayerCmd:play:<url>`
6. WiiM plays; compute board coordinates but carries no audio

NEXT cycles stations at the current city, then hops to the next nearest city (visited set, max 20 hops).

---

## ESP32 Track Reference

### Architecture diagram (current hardware)

```
┌─────────────────────────────────────────────────────────────────┐
│                        Picture Frame                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │     Physical Map + Capacitive Touch Panel Overlay         │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │ USB                               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Touch USB Controller → ESP32-S3-Long (USB Host mode)     │  │
│  │  5V via PMU OTG boost (SY6970)                            │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │ WiFi
              ┌───────────────┴───────────────┐
              ▼                               ▼
    ┌─────────────────┐             ┌─────────────────┐
    │  Radio.garden   │             │  WiiM Speaker   │
    └─────────────────┘             └─────────────────┘
```

### Source files

| File | Purpose |
|------|---------|
| `main.cpp` | Entry point, callback wiring |
| `display.cpp/h` | AMOLED rendering (Arduino_GFX) |
| `builtin_touch.cpp/h` | Built-in touchscreen (I2C, interrupt-driven) |
| `usb_touch.cpp/h` | USB HID touch panel (55" IR frame) |
| `radio_client.cpp/h` | Radio.garden API client, station caching, next-city hopping |
| `linkplay_client.cpp/h` | WiiM control via LinkPlay HTTPS API |
| `places_db.cpp/h` | Places database from LittleFS |
| `ui_state.cpp/h` | Slice selection, playback state, marker tracking |
| `world_map.cpp/h` | RLE bitmap decompression and optimized drawing |
| `menu.cpp/h` | Touch menu (volume, pause, favorites, history, sleep, settings) |
| `favorites.cpp/h` | LittleFS JSON, paginated list |
| `history.cpp/h` | Ring buffer of last 20, auto-record, dedup |
| `settings.cpp/h` | WiiM mDNS discovery, multiroom, zoom |
| `theme.h` | Colors, fonts, icons, layout constants |
| `button_handler.cpp/h` | Multi-action button (short/long/double-tap) |
| `udp_log.cpp/h` | UDP broadcast logging (port 9999) for USB Host mode |
| `pins_config.h` | Hardware pin definitions |
| `config.h` | WiFi, WiiM IP (git-ignored) |

### Building

```bash
cd esp32
cp src/config.example.h src/config.h         # edit WiiM IP
pio run -e t-display-s3-long -t upload       # P1
pio run -e t-display-s3-long -t uploadfs     # places.bin → LittleFS
pio run -e usb-touch -t upload               # P2 (external IR frame)
```

### Serial commands (testing)

```
W:192.168.0.33  # Set WiiM IP
P:<url>         # Play stream URL directly
S               # Stop
V:50            # Volume 50%
?               # WiiM status JSON
L:48.21,16.37   # Lookup nearest place
D:10            # Dump first 10 places
T:512,300       # Simulate touch (server 1024×600 coords)
```

### Display system (P1)

- **Hardware**: AXS15231B QSPI AMOLED, 180×640, portrait (rotation 0 — other rotations fade/crash).
- **Layout**: map 180×580 full-width, status bar 180×60 (3 lines: city+count, station, [STOP][NEXT]).
- **Longitude slices**: Americas (-150 to -30), Europe/Africa (-30 to 60, default), Asia (60 to 150), Pacific (wraps). Button 1 cycles.
- **Zoom**: 1x–5x, double-tap cycles, Settings stores level. Tile data in `esp32/data/maps/zoom{2,3,4,5}.bin`.

### Touch system

**Built-in (P1)**: AXS15231B, I2C addr 0x3B, INT pin GPIO 11 (FALLING). Read command `{0xB5, 0xAB, 0xA5, 0x5A, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00}`. Event extraction: `temp_buf[2] >> 6` → 0=DOWN, 1=UP, 2=CONTACT. X/Y bytes swapped vs LILYGO macros (bytes 4:5 = portrait X, bytes 2:3 = portrait Y).

**USB IR frame (P2)**: VID 1FF7 PID 0013, EP 0x83 on interface 1, 8-byte reports. Format: `byte0=0x01` (report ID), `byte1=0x01/0x00` (down/up), `bytes 2-5 = X,Y` (LE uint16, 0–32767). Must claim both HID interfaces; touch data only on interface 1. Uses ESP-IDF `usb/usb_host.h`.

### Hardware pin map

**Display (QSPI)**: CS=12, SCK=17, D0=13, D1=18, D2=21, D3=14, RST=16, BL=1
**Touch (I2C)**: SDA=15, SCL=10, INT=11, RST=16 (shared with display!)
**Button 1**: GPIO 0 (short=region, long=stop, double=next)
**Button 2**: GPIO 21 — **DISABLED**, conflicts with TFT_QSPI_D2

### Critical notes

- **Shared reset GPIO 16**: never reset after display init — touch init must skip it.
- **Rotation 0 only**: rotations 1/3 fade/crash.
- **WiiM is HTTPS on 443, self-signed**: `WiFiClientSecure` + `setInsecure()`. Port 80 is refused.
- **Radio.garden**: use HTTP/1.0 (ESP32 TLS doesn't handle chunked well). Station URL is `/listen/{slug}/{id}` — the ID is the **second** path segment. Stream URL is a redirect. `DynamicJsonDocument(16384)` for station lists.
- **Libraries pinned**: Arduino_GFX 1.3.7 (in `esp32/lib/`, manually patched so `writeFastHLine` uses `writeFillRectPreclipped` — drops map draw from ~5s to ~150ms), Arduino_DriveBus 1.1.12, ArduinoJson 6.21, WiFiManager (tzapu).
- **PMU (SY6970) startup**: `IIC_WriteC8D8(0x6A, 0x00, 0B00111111)` and `IIC_WriteC8D8(0x6A, 0x09, 0B01100100)`.
- **OTG 5V boost** for USB Host: REG03 (0x03) bit 5 — NOT REG01. REG07 bits [5:4] = 00 (disable watchdog, else regs reset ~40s). REG0A 0x80 = 5.15V.

### Serial handling gotcha

When multiple modules handle serial, use `Serial.peek()` first to avoid consuming commands meant for others:

```cpp
char cmd = Serial.peek();
if (cmd != 'M' && cmd != 'Y') return;
String line = Serial.readStringUntil('\n');
```

---

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

## LinkPlay API (WiiM)

Base: `https://<wiim-ip>/httpapi.asp?command=<cmd>` (HTTPS, port 443, self-signed cert).

| Command | Description |
|---|---|
| `getPlayerStatus` | Status + track info (JSON; `vol` is a string) |
| `setPlayerCmd:play:<url>` | Play audio URL |
| `setPlayerCmd:pause` / `resume` / `onepause` / `stop` | Transport |
| `setPlayerCmd:prev` / `next` | Track nav |
| `setPlayerCmd:vol:<0-100>` | Volume |
| `setPlayerCmd:mute:<0|1>` | Mute |
| `setPlayerCmd:equalizer:<mode>` | EQ: off/classic/popular/jazzy/vocal |
| `setPlayerCmd:loopmode:<0-4>` | 0=seq, 1=repeat-all, 2=repeat-one, 3=shuffle, 4=shuffle-repeat |
| `setSleepTimer:<seconds>` | Auto-shutoff (seconds, not minutes) |
| `getStatusEx` | Extended device info |
| `multiroom:getSlaveList` / `multiroom:Ungroup` | Multiroom group mgmt |

References: [AndersFluur/LinkPlayApi](https://github.com/AndersFluur/LinkPlayApi), [Arylic HTTP API](https://developer.arylic.com/httpapi/).

---

## Tools

| File | Purpose |
|------|---------|
| `tools/compile_places.py` | Download Radio.garden places → `places.bin` (binary, ~634 KB, 52 bytes/place). Header is `RGPL`, version 1, uint32 count. |
| `tools/generate_map_bitmaps.py` | Natural Earth coastlines → `esp32/src/world_map_data.h` (RLE) + `esp32/data/maps/zoom{2–5}.bin` |
| `tools/generate_tiled_map.py` | Tileable A3 PDF of the world map for tracing onto glass |

`places.bin` format (also used as-is by the Linux port):

```
Header (16 B): magic "RGPL", uint16 version, uint32 count, 6 B reserved
Place  (52 B): char[16] id, int16 lat*100, int16 lon*100, char[28] name, char[4] country
```

---

## Linux Track (TBD)

The Linux port targets an Orange Pi Zero 3 and will likely re-use:
- `places.bin` as-is (same format)
- LinkPlay HTTPS client (trivial — `requests.get(url, verify=False)`)
- Radio.garden client (straightforward `requests` — no chunked-encoding workarounds needed)
- evdev (`/dev/input/eventN`) for the 55" IR touch frame

Scaffolding and direction still being decided. The ESP32 firmware is the working spec.

---

## Repo Layout

```
RadioWall/
├── esp32/              # ESP32 firmware (reference track)
├── linux/              # Linux SBC port (active track — TBD)
├── tools/              # places compiler, map bitmap gen, tiled PDF
├── archive/            # early prototype assets + historical design docs
├── CLAUDE.md
└── readme.md
```
