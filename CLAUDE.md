# CLAUDE.md - RadioWall Project Context

## Project Overview

RadioWall is an interactive physical world map that plays local radio stations when you touch a location. Touch Vienna → hear Austrian radio. Touch Tokyo → hear Japanese radio.

**Key concept**: No display/screen on the map itself. A beautiful physical paper/cloth map sits behind an invisible capacitive touch layer. The only screen is a small "Now Playing" display on the ESP32.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Picture Frame                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │     Physical Map + Capacitive Touch Panel Overlay         │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │ USB                               │
│                              ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Touch USB Controller → ESP32-S3-Long (USB Host mode)     │  │
│  │                         ┌─────────────────┐               │  │
│  │                         │ Now Playing:    │               │  │
│  │                         │ Radio Wien      │               │  │
│  │  5V Power (via pins) →  │ Vienna, Austria │               │  │
│  │                         └─────────────────┘               │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │ WiFi + MQTT
                              ▼
                    ┌─────────────────┐
                    │  Home Server    │  N100 (Docker)
                    │  - Radio.garden │
                    │  - UPnP control │
                    │  - Mosquitto    │
                    └─────────────────┘
                              │ UPnP/DLNA
                              ▼
                    ┌─────────────────┐
                    │  WiiM Amp Pro   │  "Wohnzimmer oben"
                    │       🔊        │
                    └─────────────────┘
```

## Hardware

| Component | Model | Status |
|-----------|-------|--------|
| Touch Panel | 9" Capacitive (XY-PG9020-FPC-A17) with USB controller | ✅ Have |
| ESP32 | LILYGO T-Display-S3-Long (3.4" AMOLED, 640×180) | ✅ Have |
| Server | N100 mini PC | ✅ Running |
| Speaker | WiiM Amp Pro (UPnP/DLNA) — name: "Wohnzimmer oben" | ✅ Running |
| USB-C OTG adapter | USB-A Female → USB-C Male | 📦 Ordered |
| USB-C breakout | For powering ESP32 via 5V pin | 📦 Ordered |
| LiPo Battery | 3000mAh 3.7V, JST 1.25mm connector | 📦 Ordered |

### ESP32 Power Setup
- USB-C port is used for touch panel (USB Host mode)
- Power via 5V + GND pins (from USB breakout or battery)
- Battery connector: JST-GH 1.25mm 2-pin

## Server Deployment (Docker)

The server runs on the N100 via Docker Compose. No host packages needed.

### Running
```bash
cd /home/anton/projects/RadioWall
docker compose up -d              # Start everything
docker compose down               # Stop everything
docker compose up -d --build      # Rebuild after code changes
docker compose logs -f            # Follow logs
docker compose logs radiowall     # Server logs only
```

### Containers
| Service | Image | Networking | Purpose |
|---------|-------|------------|---------|
| mosquitto | eclipse-mosquitto:2 | host | MQTT broker on port 1883 |
| radiowall | Built from server/Dockerfile | host | Python server (Radio.garden + UPnP + MQTT) |

Host networking is required for UPnP/SSDP multicast speaker discovery.

### Testing with simulated touch
```bash
# From the server:
docker exec radiowall-mosquitto-1 mosquitto_pub -t "radiowall/touch" -m '{"x":558,"y":193}'

# Or if mosquitto-clients is installed on host:
mosquitto_pub -t "radiowall/touch" -m '{"x":558,"y":193}'
```

### Server IP / MQTT Broker Address
- LAN: `192.168.0.69:1883`
- Tailscale: `100.96.250.109:1883` or `server.taild7c33b.ts.net:1883`
- The ESP32 config.h `MQTT_SERVER` should be set to whichever of these is reachable

## Software Components

### 1. Server (Python) - `server/` — ✅ DONE
Runs in Docker on N100. Handles the heavy lifting.

**Files:**
- `server/main.py` - Orchestration: loads config, wires MQTT callbacks, runs event loop
- `server/radio_garden.py` - API client with place caching and nearest-station search
- `server/coordinates.py` - Pixel X/Y → lat/long conversion (equirectangular projection)
- `server/upnp_streamer.py` - UPnP/DLNA discovery and playback (async_upnp_client)
- `server/mqtt_handler.py` - MQTT pub/sub (paho-mqtt v2.x with CallbackAPIVersion.VERSION1)
- `server/config.yaml` - Runtime config (not in git, copy from config.example.yaml)
- `server/Dockerfile` - Container build

**Known quirks:**
- Radio.garden channel data is nested: `channel["page"]["url"]` and `channel["page"]["title"]`
- Stream URL resolution: only follows first redirect to avoid SSL errors with some stream servers
- UPnP discovery is non-fatal at startup; retries on first touch if no speaker found
- paho-mqtt v2.x requires `CallbackAPIVersion.VERSION1` in Client constructor

### 2. ESP32 Firmware (C++/Arduino) - `esp32/` — 🔧 SKELETON
Runs on T-Display-S3-Long. Files exist but need hardware testing and iteration.

**Files:**
- `esp32/src/main.cpp` - Entry point, wires callbacks between modules
- `esp32/src/usb_touch.cpp/.h` - USB Host HID reading (skeleton + serial simulation `T:x,y`)
- `esp32/src/mqtt_client.cpp/.h` - WiFi + MQTT with auto-reconnect
- `esp32/src/display.cpp/.h` - AMOLED UI (TFT_eSPI), auto-dimming after timeout
- `esp32/src/config.example.h` - Template for WiFi/MQTT/touch settings
- `esp32/platformio.ini` - PlatformIO build config for T-Display-S3-Long

**To work on ESP32 firmware:**
1. Copy `config.example.h` to `config.h`
2. Fill in WiFi credentials and MQTT server IP
3. `pio run -t upload` to flash
4. `pio device monitor` for serial output
5. Send `T:512,300` over serial to simulate touch (no hardware needed)

**What's NOT done in ESP32:**
- `usb_touch.cpp` is a skeleton — real USB Host HID parsing needs the actual touch panel connected via OTG to inspect the HID descriptor and report format
- Display uses TFT_eSPI directly; LVGL is available in platformio.ini for a nicer UI later

## MQTT Topics

```
radiowall/touch       ESP32 → Server    {"x": 512, "y": 300, "ts": 1234567890}
radiowall/nowplaying  Server → ESP32    {"station": "Radio Wien", "location": "Vienna, Austria", "country": "AT"}
radiowall/status      Server → ESP32    {"state": "playing"} or {"state": "stopped"} or {"state": "error", "msg": "..."}
radiowall/command     ESP32 → Server    {"cmd": "stop"} or {"cmd": "replay"}
```

## Radio.garden API

Unofficial API (no auth required):

```bash
# List all places with radio stations (~12,500 places)
GET http://radio.garden/api/ara/content/places
# Returns: {"data": {"list": [{"id": "IgQ9XxkV", "title": "Vienna", "country": "Austria", "geo": [16.37, 48.21], "size": 102}, ...]}}
# NOTE: geo is [longitude, latitude] not [lat, long]!

# Get stations at a place
GET http://radio.garden/api/ara/content/page/{place_id}/channels
# Returns: {"data": {"content": [{"items": [{"page": {"url": "/listen/station-name/ID", "title": "Station Name", ...}}, ...]}]}}

# Get stream URL (redirects to actual stream)
GET http://radio.garden/api/ara/content/listen/{station_id}/channel.mp3
```

## Coordinate Conversion & Calibration

Map uses equirectangular projection (Plate Carrée). Conversion is linear:

```python
longitude = (x / touch_width) * 360 - 180   # -180 to +180
latitude = 90 - (y / touch_height) * 180    # +90 to -90
```

Calibration in `server/config.yaml`:
```yaml
calibration:
  touch_min_x: 0
  touch_max_x: 1024   # Verify with actual panel (evtest / serial)
  touch_min_y: 0
  touch_max_y: 600    # Verify with actual panel
  map_north: 90       # Adjust if map is cropped
  map_south: -90
  map_west: -180
  map_east: 180
```

Touch resolution is fixed by the panel's controller chip, NOT the physical size. A 9" and 55" panel with the same controller report the same coordinate range. Calibrate by touching corners and reading raw values.

## Development Phases

### Phase 0: Hardware Testing ⏳
- [x] Test touch panel on desktop PC (moves cursor — works)
- [ ] Read touch panel raw coordinates (evtest)
- [ ] Test ESP32 display basics
- [x] Test WiiM UPnP discovery (found "Wohnzimmer oben")

### Phase 1: Server Application ✅
- [x] Radio.garden API client (with caching)
- [x] Coordinate conversion with calibration config
- [x] UPnP/DLNA streaming to WiiM
- [x] MQTT handler
- [x] Docker Compose deployment
- [x] End-to-end test: simulated touch → station lookup → WiiM playback

### Phase 2: ESP32 Firmware 🔧
- [ ] USB Host mode for touch panel (needs OTG adapter)
- [x] MQTT client (skeleton with WiFi reconnect)
- [x] Display UI for "Now Playing" (skeleton)
- [x] Power management (display dimming)
- [ ] Test on actual hardware
- [ ] Flash and iterate

### Phase 3: Integration
- [ ] End-to-end: touch panel → ESP32 → MQTT → server → WiiM
- [ ] Calibration tool (touch corners → save to config)
- [ ] Error handling (ocean touches, no stations, WiFi drops)

### Phase 4: Production (Future)
- [ ] Large PCAP touch foil (55"+)
- [ ] Frame design
- [ ] Final installation

## Key Technical Notes

### T-Display-S3-Long Specifics
- Display: 3.4" AMOLED, 640×180, capacitive touch (built-in, separate from map touch)
- USB-C has OTG capability via SY6970 chip
- Enable OTG in code: `PMU.enableOTG();`
- Power via 5V pin when USB-C used for touch panel
- Battery: JST-GH 1.25mm 2-pin, 3.7V LiPo
- When on battery, must set GPIO15 HIGH for display backlight

### Touch Panel (XY-PG9020)
- 9" capacitive touch, I2C internally (GT911 or similar chip)
- USB controller board converts to USB HID
- Appears as standard HID touch device
- Resolution: ~1024×600 (verify with actual device using evtest)

### Power Budget
- ESP32 + display + touch: ~110-180mA active, ~35-65mA idle
- 3000mAh battery → ~1-2 days active, ~2-4 days idle

## File Structure

```
RadioWall/
├── CLAUDE.md              # This file
├── README.md              # Project documentation
├── docker-compose.yml     # Docker Compose (mosquitto + radiowall server)
├── .dockerignore
├── docs/
│   └── hardware_testing.md
├── mosquitto/
│   └── mosquitto.conf     # Mosquitto broker config
├── server/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.example.yaml
│   ├── config.yaml        # Runtime config (git-ignored)
│   ├── radio_garden.py
│   ├── coordinates.py
│   ├── upnp_streamer.py
│   ├── mqtt_handler.py
│   └── main.py
├── esp32/
│   ├── platformio.ini
│   └── src/
│       ├── config.example.h
│       ├── config.h        # Runtime config (git-ignored)
│       ├── main.cpp
│       ├── usb_touch.cpp / .h
│       ├── mqtt_client.cpp / .h
│       └── display.cpp / .h
└── playground.ipynb       # Original prototype (reference only)
```

## Current Status

**Server**: ✅ Running in Docker on N100, end-to-end tested (touch sim → Radio.garden → WiiM playback).

**ESP32**: 🔧 Skeleton firmware written. Needs:
1. `config.h` created with WiFi creds + MQTT server IP
2. Flash to ESP32 and verify display works
3. USB Host touch reading once OTG adapter arrives

**Waiting for**: USB-C OTG adapter and USB-C breakout board (shipping).

**Next steps**:
1. Flash ESP32 firmware and test display + MQTT connection
2. Read touch panel raw coordinates to verify calibration values
3. Complete USB Host HID parsing when OTG adapter arrives
