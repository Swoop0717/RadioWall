# CLAUDE.md - RadioWall Project Context

> Technical reference for AI assistants working on this codebase.

## Project Overview

RadioWall is an interactive physical world map that plays local radio stations when you touch a location. Touch Vienna → hear Austrian radio. Touch Tokyo → hear Japanese radio.

**The Vision**: A physical paper/cloth map sits behind invisible capacitive touch glass. No screen on the map — just a small ESP32 display showing "Now Playing" info.

**Current State**: **Prototype 1** — using the ESP32's built-in touchscreen as a temporary map interface while waiting for USB adapters. The full system is working end-to-end.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Picture Frame                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │     Physical Map + Capacitive Touch Panel Overlay         │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │ USB                               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Touch USB Controller → ESP32-S3-Long (USB Host mode)     │  │
│  │                         ┌─────────────────┐               │  │
│  │                         │ [World Map]     │               │  │
│  │  5V Power (via pins) →  │ Region: Europe  │               │  │
│  │                         │ [STOP]   [NEXT] │               │  │
│  │                         └─────────────────┘               │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │ WiFi + MQTT
                              ▼
                    ┌─────────────────┐
                    │  Home Server    │  Docker on N100
                    │  - Mosquitto    │
                    │  - Radio.garden │
                    │  - UPnP control │
                    └─────────────────┘
                              │ UPnP/DLNA
                              ▼
                    ┌─────────────────┐
                    │  WiiM Amp Pro   │
                    └─────────────────┘
```

## Current Status: Prototype 1

> **Prototype 1** uses the ESP32's built-in touchscreen + world map display as a temporary stand-in for the external touch panel + physical map. This lets us test the full stack while waiting for USB adapters.

| Component | Status |
|-----------|--------|
| Server (Docker) | ✅ Running, end-to-end tested |
| ESP32 Display | ✅ Working (Arduino_GFX + AXS15231) |
| ESP32 Built-in Touch | ✅ Working (I2C interrupt-driven) |
| ESP32 MQTT | ✅ Connected, pub/sub working |
| World Map Rendering | ✅ RLE bitmaps (Prototype 1 only) |
| USB Touch Panel | 🔧 Skeleton, waiting for OTG adapter |
| End-to-End Flow | ✅ Touch → MQTT → Server → WiiM |

### TODO: Prototype 2 (External Touch Panel)

- [ ] Test USB-C OTG adapter when it arrives
- [ ] Implement USB Host HID in `usb_touch.cpp` (inspect HID descriptor, parse reports)
- [ ] Build calibration tool (touch 4 corners → calculate transform matrix)
- [ ] Test with 9" touch panel over a printed map
- [ ] Simplify ESP32 display to "Now Playing" only (remove map rendering)
- [ ] Add `USE_BUILTIN_TOUCH 0` mode that skips map UI

### TODO: Standalone Mode (No Server)

The final product needs no server — just ESP32 + WiiM Mini + WiFi.

**New files to create:**
| File | Purpose |
|------|---------|
| `tools/compile_places.py` | Download Radio.garden places → `places.bin` (~500KB) |
| `esp32/src/radio_client.cpp` | Load places from flash, find nearest, call Radio.garden API |
| `esp32/src/upnp_client.cpp` | UPnP/DLNA SOAP commands to control WiiM |

**Tasks:**
- [ ] Create places compiler tool (Python)
- [ ] Implement ESP32 Radio.garden client (HTTPS, JSON parsing)
- [ ] Implement ESP32 UPnP client (SSDP discovery, SOAP Play/Stop)
- [ ] Add `#define STANDALONE_MODE` to switch between MQTT and standalone
- [ ] Store WiiM IP in config or auto-discover via SSDP
- [ ] Remove MQTT dependency in standalone mode

**Data structures for places.bin:**
```cpp
struct Place {
    char id[12];        // Radio.garden place ID
    int16_t lat_x100;   // Latitude × 100 (e.g., 48.21° → 4821)
    int16_t lon_x100;   // Longitude × 100
    char name[32];      // City name
    char country[3];    // Country code
};
// ~50 bytes × 12,500 places = ~625KB
```

**UPnP flow:**
```cpp
// 1. Discover WiiM (or use configured IP)
String wiim_ip = ssdp_discover("urn:schemas-upnp-org:device:MediaRenderer:1");

// 2. Send stream URL
upnp_set_uri(wiim_ip, stream_url, "Radio Wien - Vienna");

// 3. Play
upnp_play(wiim_ip);
```

### TODO: Production (Phase 5)

- [ ] Source large PCAP touch foil (55"+)
- [ ] Design frame with hidden electronics compartment
- [ ] High-quality equirectangular map print
- [ ] Power solution (USB wall adapter or LiPo with charging)

**Waiting for**: USB-C OTG adapter + breakout board (ordered).

---

## Target Architecture: Standalone ESP32

The final product requires **no server** — ESP32 handles everything:

```
Touch Panel → ESP32-S3 → WiFi → Radio.garden API
                ↓                     ↓
         [Now Playing]           Stream URL
                                      ↓
                              UPnP → WiiM Mini 🔊
```

**Why this works:**
- ESP32 tells WiiM "play this URL" via UPnP
- WiiM fetches the audio stream directly from the internet
- ESP32 just coordinates — no audio processing needed

---

## Server (Python)

### Files

| File | Purpose |
|------|---------|
| `server/main.py` | Orchestration, MQTT callbacks, event loop |
| `server/radio_garden.py` | API client, place caching, stream validation |
| `server/coordinates.py` | Pixel X/Y → lat/lon conversion |
| `server/upnp_streamer.py` | UPnP/DLNA discovery and playback |
| `server/mqtt_handler.py` | MQTT pub/sub (paho-mqtt v2.x) |
| `server/config.yaml` | Runtime config (git-ignored) |

### Running

```bash
cd /path/to/RadioWall
docker compose up -d              # Start
docker compose logs -f            # Follow logs
docker compose up -d --build      # Rebuild after changes
```

### Testing

```bash
# Simulate touch
docker exec radiowall-mosquitto-1 mosquitto_pub \
  -t "radiowall/touch" -m '{"x":558,"y":193}'

# Commands
mosquitto_pub -t "radiowall/command" -m '{"cmd":"next"}'
mosquitto_pub -t "radiowall/command" -m '{"cmd":"stop"}'
```

### Known Quirks

- Radio.garden API: `geo` is `[longitude, latitude]` (not lat/lon!)
- Channel data nested: `channel["page"]["url"]` and `channel["page"]["title"]`
- Stream URL resolution: Only follows first redirect (avoids SSL errors)
- paho-mqtt v2.x requires `CallbackAPIVersion.VERSION1` in Client constructor

---

## ESP32 Firmware (C++/Arduino)

### Files

| File | Purpose |
|------|---------|
| `main.cpp` | Entry point, callback wiring |
| `display.cpp/h` | AMOLED rendering (Arduino_GFX) |
| `builtin_touch.cpp/h` | Built-in touchscreen (I2C, interrupt-driven) |
| `usb_touch.cpp/h` | USB HID touch panel (skeleton) |
| `mqtt_client.cpp/h` | WiFi + MQTT with auto-reconnect |
| `ui_state.cpp/h` | Slice selection, playback state |
| `world_map.cpp/h` | RLE bitmap decompression and drawing |
| `button_handler.cpp/h` | Physical button debouncing |
| `pins_config.h` | Hardware pin definitions |
| `config.h` | WiFi, MQTT settings (git-ignored) |

### Building

```bash
cd esp32
cp src/config.example.h src/config.h
# Edit config.h with WiFi/MQTT settings

pio run -t upload
pio device monitor
```

### Serial Commands (Testing)

```
T:512,300    # Simulate touch at (512, 300) in server coordinates
```

---

## Display System (Prototype 1)

> **Note**: The world map on the ESP32 display is temporary for Prototype 1. In the final version, the map is physical and the ESP32 only shows "Now Playing" info.

### Hardware

- **Display**: AXS15231B QSPI AMOLED, 180×640 pixels
- **Orientation**: Portrait mode (rotation 0)
- **Driver**: Arduino_AXS15231 from Arduino_GFX library
- **Touch**: Integrated in display IC, I2C address 0x3B

### Screen Layout (Portrait)

```
┌──────────────────┐  (0,0)
│ ┌──────────────┐ │
│ │              │ │  Map Area: 160×560
│ │  Map Bitmap  │ │  Position: (10, 10)
│ │  (current    │ │
│ │   slice)     │ │  Touch here → lat/lon → server
│ │              │ │
│ └──────────────┘ │
├──────────────────┤  y=580
│ Region: Europe   │  Status Bar: 180×60
│ Station | City   │
│ [STOP]    [NEXT] │  Touch buttons
└──────────────────┘  (180,640)
```

### Longitude Slices

The world is divided into 4 vertical slices:

| Index | Name | Longitude Range |
|-------|------|-----------------|
| 0 | Americas | -150° to -30° |
| 1 | Europe/Africa | -30° to 60° (default) |
| 2 | Asia | 60° to 150° |
| 3 | Pacific | 150° to -150° (wraps) |

Button 1 (GPIO 0) cycles through slices.

### Map Data Generation

```bash
cd tools
pip install -r requirements.txt
python generate_map_bitmaps.py
```

Downloads Natural Earth 1:110m coastline data, renders 160×560 bitmaps, RLE compresses to `esp32/src/world_map_data.h` (~20KB total).

---

## Touch System

### Prototype 1: Built-in Touch (AXS15231B)

Used for testing while waiting for USB adapters.

- **I2C Address**: 0x3B
- **Interrupt Pin**: GPIO 11 (FALLING edge)
- **Read Command**: `{0xB5, 0xAB, 0xA5, 0x5A, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00}`

### Prototype 2: USB Touch Panel (TODO)

The 9" capacitive touch panel (XY-PG9020) connects via USB and appears as HID device.

- **File**: `usb_touch.cpp` (currently skeleton)
- **TODO**: Enable USB Host mode, enumerate HID device, parse touch reports
- **Testing**: Use `evtest` on Linux PC to inspect HID report format first

### Touch Coordinate Flow (Prototype 1)

```
Display Touch (180×640 portrait)
         │
         ▼
Zone Detection
  ├─ y < 580 → Map Area
  │     │
  │     ▼
  │   Normalize to map bounds (10-170, 10-570)
  │     │
  │     ▼
  │   Convert to lat/lon using current slice
  │     │
  │     ▼
  │   Convert to server coords (1024×600)
  │     │
  │     ▼
  │   MQTT publish to radiowall/touch
  │
  └─ y >= 580 → Status Bar
        │
        ▼
      Button detection (x < 90 = STOP, else NEXT)
        │
        ▼
      MQTT publish to radiowall/command
```

### Coordinate Conversion Code

```cpp
// In builtin_touch.cpp, map area touch handling:

// Normalize to map bounds
float norm_x = (portrait_x - 10) / 160.0f;  // 0.0 to 1.0
float norm_y = (portrait_y - 10) / 560.0f;  // 0.0 to 1.0

// X maps to latitude (-90° to 90°)
float lat = -90.0f + norm_x * 180.0f;

// Y maps to longitude within current slice
float lon = slice.lon_min + norm_y * (slice.lon_max - slice.lon_min);

// Convert to server's 1024×600 equirectangular space
int server_x = (int)((lon + 180.0f) / 360.0f * 1024.0f);
int server_y = (int)((90.0f - lat) / 180.0f * 600.0f);
```

### Coordinate Conversion (Prototype 2 — Simpler)

In Prototype 2 with external touch panel + physical map:

```cpp
// USB touch panel reports raw coordinates (e.g., 0-1024, 0-600)
// These map directly to the server's equirectangular space
// No slice conversion needed — the physical map shows everything

int server_x = touch_x;  // Direct mapping (after calibration)
int server_y = touch_y;
mqtt_publish_touch(server_x, server_y);
```

Calibration will handle any offset/scale differences between the touch panel and map boundaries.

---

## MQTT Protocol

### Topics

| Topic | Direction | Payload |
|-------|-----------|---------|
| `radiowall/touch` | ESP32 → Server | `{"x": 512, "y": 300, "ts": ...}` |
| `radiowall/nowplaying` | Server → ESP32 | `{"station": "...", "location": "...", "country": "..."}` |
| `radiowall/status` | Server → ESP32 | `{"state": "playing"}` / `"stopped"` / `"loading"` / `"error"` |
| `radiowall/command` | ESP32 → Server | `{"cmd": "stop"}` / `"next"` / `"replay"}` |

---

## Hardware Pin Definitions

### Display (QSPI)

| Pin | GPIO | Notes |
|-----|------|-------|
| CS | 12 | |
| SCK | 17 | |
| D0 | 13 | MOSI |
| D1 | 18 | MISO |
| D2 | 21 | ⚠️ Conflicts with Button 2 |
| D3 | 14 | |
| RST | 16 | Shared with touch! |
| BL | 1 | Backlight (PWM) |

### Touch (I2C)

| Pin | GPIO |
|-----|------|
| SDA | 15 |
| SCL | 10 |
| INT | 11 |
| RST | 16 | Shared with display! |

### Buttons

| Button | GPIO | Notes |
|--------|------|-------|
| Button 1 | 0 | Cycle longitude slice |
| Button 2 | 21 | ⚠️ DISABLED - conflicts with TFT_QSPI_D2 |

---

## Critical Technical Notes

### ⚠️ Shared Reset Pin (GPIO 16)

Display and touch share the same reset pin. **NEVER reset GPIO 16 after display initialization** — it will crash the display.

```cpp
// In builtin_touch_init():
// NOTE: Do NOT reset GPIO 16 here - display_init() already reset it!
```

### ⚠️ Display Rotation

- Rotation 0 (portrait) is **stable**
- Rotations 1 and 3 cause display fading/crashing issues
- All UI code assumes portrait mode (180×640)

### ⚠️ Button 2 Disabled

GPIO 21 is used for both Button 2 and TFT_QSPI_D2 (display data line). Using Button 2 causes display glitches. Use touch-based STOP button instead.

### Library Versions

| Library | Version | Notes |
|---------|---------|-------|
| Arduino_GFX | 1.3.7 | In `esp32/lib/` folder |
| Arduino_DriveBus | 1.1.12 | In `esp32/lib/` folder |
| PubSubClient | 2.8 | MQTT client |
| ArduinoJson | 6.21 | JSON parsing |

Newer Arduino_GFX versions (1.6+) require newer ESP32 framework and won't compile.

### Power Management

At startup, configure the SY6970 PMU:

```cpp
IIC_WriteC8D8(0x6A, 0x00, 0B00111111);  // Disable ILIM, max current
IIC_WriteC8D8(0x6A, 0x09, 0B01100100);  // Turn off BATFET
```

---

## Radio.garden API

Unofficial API (no auth required):

```bash
# List all places (~12,500)
GET http://radio.garden/api/ara/content/places
# Response: {"data": {"list": [{"id": "...", "title": "Vienna", 
#            "country": "Austria", "geo": [16.37, 48.21], "size": 102}]}}
# NOTE: geo is [LONGITUDE, LATITUDE] not [lat, lon]!

# Get stations at a place
GET http://radio.garden/api/ara/content/page/{place_id}/channels

# Get stream URL (redirects to actual stream)
GET http://radio.garden/api/ara/content/listen/{station_id}/channel.mp3
```

---

## File Structure

```
RadioWall/
├── docker-compose.yml
├── mosquitto/
│   └── mosquitto.conf
├── server/
│   ├── Dockerfile
│   ├── main.py
│   ├── radio_garden.py
│   ├── coordinates.py
│   ├── upnp_streamer.py
│   ├── mqtt_handler.py
│   ├── config.example.yaml
│   └── requirements.txt
├── esp32/
│   ├── platformio.ini
│   ├── lib/
│   │   ├── Arduino_GFX-1.3.7/
│   │   └── Arduino_DriveBus-1.1.12/
│   └── src/
│       ├── main.cpp
│       ├── display.cpp/h
│       ├── builtin_touch.cpp/h
│       ├── usb_touch.cpp/h
│       ├── mqtt_client.cpp/h
│       ├── ui_state.cpp/h
│       ├── world_map.cpp/h
│       ├── world_map_data.h        # Generated
│       ├── button_handler.cpp/h
│       ├── pins_config.h
│       └── config.example.h
├── tools/
│   ├── generate_map_bitmaps.py
│   └── requirements.txt
└── docs/
    ├── hardware_testing.md
    └── world_map_implementation.md
```

---

## Common Tasks

### Implement USB Touch Panel (Prototype 2)

1. Connect touch panel via OTG adapter
2. On Linux PC, use `evtest` to find HID report format
3. Update `usb_touch.cpp` with proper HID parsing
4. Test with `USE_BUILTIN_TOUCH 0` in config.h
5. Build calibration routine

### Simplify Display for Prototype 2

When using external touch panel, the ESP32 display only needs to show:
- Station name
- Location
- Playback status
- Maybe STOP/NEXT buttons

Remove map rendering code path when `USE_BUILTIN_TOUCH 0`.

### Add a new MQTT command

1. Add handler in `server/main.py` `_handle_command()`
2. Add case in `esp32/src/main.cpp` if ESP32 needs to send it
3. Update MQTT topics table in this doc

### Change map slice definitions

1. Edit `esp32/src/ui_state.cpp` `UIState::UIState()` constructor
2. Regenerate bitmaps if changing longitude ranges: `python tools/generate_map_bitmaps.py`

### Add new display screen

1. Add function in `esp32/src/display.cpp`
2. Declare in `esp32/src/display.h`
3. Call from appropriate callback in `main.cpp`

### Debug touch issues

1. Check serial output for `[Touch]` logs
2. Verify I2C address 0x3B responding
3. Check interrupt pin GPIO 11
4. Ensure display initialized first (touch won't work without it!)
