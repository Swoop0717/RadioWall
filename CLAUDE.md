# CLAUDE.md - RadioWall Project Context

> Technical reference for AI assistants working on this codebase.

## Project Overview

RadioWall is an interactive physical world map that plays local radio stations when you touch a location. Touch Vienna → hear Austrian radio. Touch Tokyo → hear Japanese radio.

**The Vision**: A physical paper/cloth map sits behind invisible capacitive touch glass. No screen on the map — just a small ESP32 display showing "Now Playing" info.

**Current State**: **ESP32 Standalone Mode** — fully working end-to-end without server. Touch map → find city → fetch Radio.garden stations → stream to WiiM via LinkPlay.

## Architecture (Standalone - No Server Required)

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
                              │ WiFi (direct)
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
    ┌─────────────────┐             ┌─────────────────┐
    │  Radio.garden   │             │  WiiM Speaker   │
    │  (stations API) │             │  (LinkPlay API) │
    └─────────────────┘             └─────────────────┘
```

**Data Flow**: Touch → ESP32 finds nearest city → fetches stations from Radio.garden → gets stream URL → sends to WiiM via LinkPlay HTTPS API

## Current Status: Prototype 1 (Fully Working)

> **Prototype 1** uses the ESP32's built-in touchscreen + world map display as a temporary stand-in for the external touch panel + physical map. **Fully functional end-to-end.**

| Component | Status |
|-----------|--------|
| ESP32 Display | ✅ Working (Arduino_GFX + AXS15231 AMOLED) |
| ESP32 Built-in Touch | ✅ Working (I2C interrupt-driven) |
| Places Database | ✅ 12,486 cities loaded from LittleFS |
| Radio.garden Client | ✅ HTTPS, JSON parsing, station caching |
| LinkPlay Client | ✅ WiiM control via HTTPS (port 443) |
| Physical Button | ✅ Multi-action: short/long/double-tap |
| Touch Buttons | ✅ STOP and NEXT in status bar |
| Map Rendering | ✅ Optimized with drawFastHLine (~4s) |
| End-to-End Flow | ✅ Touch → Places → Radio.garden → WiiM |
| Server (Docker) | ⏸️ Not needed (standalone mode) |
| USB Touch Panel | 🔧 Skeleton, waiting for OTG adapter |

### User Controls

| Input | Action |
|-------|--------|
| Touch map | Play radio from nearest city (X marker at city) |
| Touch STOP button | Stop playback |
| Touch NEXT button | Next station; hops to next city when exhausted |
| Swipe left/right | Cycle map region |
| Button short press | Cycle map region (Americas/Europe/Asia/Pacific) |
| Button long press (>800ms) | Toggle menu |
| Button double-tap (<400ms) | Next station |
| Menu → Volume | Tap-based vertical volume slider |
| Menu → Pause/Resume | Toggle pause/resume |
| Menu → Sleep Timer | Cycle: Off/15/30/60/90 min |
| Menu → Favorites | View/play/delete saved stations |
| Favorites → ADD | Save currently playing station |

### TODO: Prototype 2 (External Touch Panel)

- [ ] Test USB-C OTG adapter when it arrives
- [ ] Implement USB Host HID in `usb_touch.cpp` (inspect HID descriptor, parse reports)
- [ ] Build calibration tool (touch 4 corners → calculate transform matrix)
- [ ] Test with 9" touch panel over a printed map
- [ ] Simplify ESP32 display to "Now Playing" only (remove map rendering)
- [ ] Add `USE_BUILTIN_TOUCH 0` mode that skips map UI

### ✅ COMPLETED: Standalone Mode (No Server)

The ESP32 now works completely standalone — no server required!

**Implemented files:**
| File | Purpose |
|------|---------|
| `tools/compile_places.py` | ✅ Downloads Radio.garden places → `places.bin` (634KB) |
| `esp32/src/radio_client.cpp` | ✅ Radio.garden API client, station caching |
| `esp32/src/linkplay_client.cpp` | ✅ WiiM control via LinkPlay HTTPS API |
| `esp32/src/places_db.cpp` | ✅ Load places from LittleFS, nearest-city lookup |

**Completed tasks:**
- [x] Create places compiler tool (Python)
- [x] Implement ESP32 Radio.garden client (HTTPS, JSON parsing)
- [x] Implement LinkPlay client (simpler than UPnP, HTTPS on port 443)
- [x] Store WiiM IP in config.h (`WIIM_IP`)
- [x] Remove MQTT dependency (standalone is default)
- [x] Multi-action button support (short/long/double-tap)
- [x] Optimized map rendering with drawFastHLine()

**Note:** We use LinkPlay HTTP API instead of UPnP — simpler and works great with WiiM devices.

### TODO: Production (Phase 5)

- [ ] Source large PCAP touch foil (55"+)
- [ ] Design frame with hidden electronics compartment
- [ ] High-quality equirectangular map print
- [ ] Power solution (USB wall adapter or LiPo with charging)

**Waiting for**: USB-C OTG adapter + breakout board (ordered).

---

## ✅ Standalone Architecture (Implemented)

The ESP32 handles everything — no server required:

```
Touch Panel → ESP32-S3 → WiFi → Radio.garden API
                ↓                     ↓
         [Now Playing]           Stream URL
                                      ↓
                            LinkPlay → WiiM 🔊
```

**How it works:**
1. Touch map → ESP32 finds nearest city in places database
2. ESP32 fetches station list from Radio.garden API
3. ESP32 gets stream URL (follows redirect)
4. ESP32 sends stream URL to WiiM via LinkPlay HTTPS API
5. WiiM fetches audio stream directly from internet
6. ESP32 just coordinates — no audio processing needed

---

## Server (Python) - Optional

> **Note:** The server is no longer required. ESP32 standalone mode handles everything directly. The server code remains for reference or alternative deployment.

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
| `radio_client.cpp/h` | Radio.garden API client, station caching, next-city hopping |
| `linkplay_client.cpp/h` | WiiM control via LinkPlay HTTPS API |
| `places_db.cpp/h` | Places database from LittleFS |
| `ui_state.cpp/h` | Slice selection, playback state, marker tracking |
| `world_map.cpp/h` | RLE bitmap decompression and optimized drawing |
| `menu.cpp/h` | Touch menu system (volume, pause, favorites, sleep timer) |
| `favorites.cpp/h` | Favorites storage (LittleFS JSON), rendering, touch |
| `button_handler.cpp/h` | Multi-action button (short/long/double-tap) |
| `pins_config.h` | Hardware pin definitions |
| `config.h` | WiFi, WiiM IP settings (git-ignored) |

### Building

```bash
cd esp32
cp src/config.example.h src/config.h
# Edit config.h:
#   - WIFI_SSID, WIFI_PASSWORD
#   - WIIM_IP (find in WiiM app or router)

pio run -t upload      # Upload firmware
pio run -t uploadfs    # Upload places.bin to LittleFS
pio device monitor     # Watch serial output
```

### Serial Commands (Testing)

```
T:512,300       # Simulate touch at (512, 300) in server coordinates
W:192.168.1.50  # Set WiiM IP address
P:<url>         # Play stream URL directly
S               # Stop playback
V:50            # Set volume to 50%
?               # Get WiiM status
L:48.21,16.37   # Lookup nearest place to coordinates
D:10            # Dump first 10 places from database
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
│                  │
│   Map Bitmap     │  Map Area: 180×580 (full width)
│   (current       │  Position: (0, 0)
│    slice)        │
│   [X] = city     │  Red X marker at playing city
│                  │
├──────────────────┤  y=580
│ City, CC (2/5)   │  Status Bar: 180×60
│ Station Name     │  Line 1: city + station count (green)
│ [STOP]    [NEXT] │  Line 2: station name (white)
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

Downloads Natural Earth 1:110m coastline data, renders 180×580 bitmaps, RLE compresses to `esp32/src/world_map_data.h` (~22KB total).

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
  │   Normalize to map bounds
  │     │
  │     ▼
  │   Convert to lat/lon using current slice
  │     │
  │     ▼
  │   radio_play_at_location(lat, lon)
  │     │
  │     ▼
  │   Find nearest city → Fetch stations → Play via WiiM
  │
  └─ y >= 580 → Status Bar
        │
        ▼
      Button detection (x < 90 = STOP, else NEXT)
        │
        ▼
      radio_stop() or radio_play_next()
```

### Coordinate Conversion Code

```cpp
// In builtin_touch.cpp, map area touch handling:

// Normalize to map bounds (full width, no padding)
float norm_x = portrait_x / 179.0f;  // 0.0 to 1.0
float norm_y = portrait_y / 579.0f;  // 0.0 to 1.0

// X maps to longitude within current slice
float lon = slice.lon_min + norm_x * lon_range;

// Y maps to latitude (90° at top to -90° at bottom)
float lat = 90.0f - norm_y * 180.0f;

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

## MQTT Protocol (Legacy - Not Used in Standalone Mode)

> **Note:** MQTT is only used if connecting to the optional Docker server. Standalone mode (default) doesn't use MQTT.

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
| Button 1 | 0 | Multi-action (see below) |
| Button 2 | 21 | ⚠️ DISABLED - conflicts with TFT_QSPI_D2 |

**Button 1 Multi-Action Support:**
| Action | Timing | Function |
|--------|--------|----------|
| Short press | <800ms | Cycle map region |
| Long press | >800ms hold | STOP playback |
| Double-tap | <400ms between presses | NEXT station |

**Toggle Switch:** The physical toggle switch on the T-Display-S3-Long board is a **battery power switch**, not a GPIO input. It disconnects/connects battery power.

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
│       ├── radio_client.cpp/h      # Radio.garden API client
│       ├── linkplay_client.cpp/h   # WiiM/LinkPlay control
│       ├── places_db.cpp/h         # Places database from LittleFS
│       ├── mqtt_client.cpp/h       # Optional, for server mode
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

---

## ESP32 Standalone Mode (Implemented)

The ESP32 now works completely standalone without a server. Key files:

| File | Purpose |
|------|---------|
| `radio_client.cpp/h` | Radio.garden API client, station caching |
| `linkplay_client.cpp/h` | WiiM control via LinkPlay HTTP API |
| `places_db.cpp/h` | Load places from LittleFS, nearest-city lookup |

### WiiM / LinkPlay Quirks

**⚠️ WiiM uses HTTPS on port 443, NOT HTTP on port 80!**

```cpp
// WRONG - will get "Connection reset by peer"
WiFiClient client;
client.connect(wiim_ip, 80);

// CORRECT - WiiM uses HTTPS with self-signed certificate
WiFiClientSecure client;
client.setInsecure();  // Skip cert verification
client.connect(wiim_ip, 443);
```

- Port 80: Connection refused / reset
- Port 443: Works (HTTPS with self-signed cert)
- Port 10080: Connection refused

When accessing `https://<wiim-ip>/` in browser, you'll see an SSL warning - click "Advanced" → "Accept Risk" to proceed. This confirms HTTPS is required.

### Radio.garden API Quirks (ESP32)

**1. Chunked Transfer Encoding**

Radio.garden returns chunked responses with HTTP/1.1. ESP32's WiFiClientSecure doesn't handle this well.

```cpp
// WRONG - may get garbled/incomplete responses
client.printf("GET %s HTTP/1.1\r\n", path);

// CORRECT - HTTP/1.0 forces non-chunked response
client.printf("GET %s HTTP/1.0\r\n", path);
```

**2. Station URL Format**

The station URL in API response is `/listen/{slug}/{id}`, not `/listen/{id}`:

```
URL: /listen/radio-8/9C7CCHgB
              ↑ slug    ↑ actual ID (use this!)
```

```cpp
// Extract the ID (second part after /listen/)
String url = "/listen/radio-8/9C7CCHgB";
int slugStart = url.indexOf("/listen/") + 8;  // After "/listen/"
int idStart = url.indexOf("/", slugStart) + 1;  // After slug
String stationId = url.substring(idStart);  // "9C7CCHgB"
```

**3. Stream URL is a Redirect**

`/api/ara/content/listen/{id}/channel.mp3` returns HTTP 302 redirect, not the stream.
Parse the `Location` header to get the actual stream URL.

**4. ArduinoJson Memory**

Station list responses can be large. Use at least 16KB:

```cpp
DynamicJsonDocument doc(16384);  // 16KB for station lists
```

### Serial Command Handling

When multiple modules handle serial commands, use `Serial.peek()` to check without consuming:

```cpp
void my_serial_task() {
    if (!Serial.available()) return;

    char cmd = Serial.peek();  // Look without consuming

    // Only handle our commands
    if (cmd != 'M' && cmd != 'Y') {
        return;  // Let other handlers process it
    }

    // Now consume and process
    String line = Serial.readStringUntil('\n');
    // ...
}
```

### Serial Commands (Standalone Mode)

| Command | Description |
|---------|-------------|
| `W:<ip>` | Set WiiM IP address |
| `P:<url>` | Play stream URL directly |
| `S` | Stop playback |
| `V:<0-100>` | Set volume |
| `?` | Get WiiM status (JSON) |
| `L:<lat>,<lon>` | Lookup nearest place |
| `D:<count>` | Dump first N places |

### PlatformIO Serial Monitor

To send commands via serial monitor:

```ini
; platformio.ini
monitor_filters = esp32_exception_decoder, send_on_enter
monitor_echo = yes
```

- `send_on_enter`: Press Enter to send the line
- `monitor_echo`: See what you're typing

### Map Rendering Optimization

Map rendering uses `drawFastHLine()` instead of `drawPixel()` for better performance:

```cpp
// OLD - slow (~10+ seconds)
gfx->drawPixel(x, y, color);

// NEW - faster (~4 seconds)
gfx->drawFastHLine(x, y, width, color);
```

The RLE-compressed map data is decoded into horizontal line segments, reducing SPI transactions from ~90,000 to ~10,000.

**Note:** For truly instant rendering (<100ms), would need PSRAM framebuffer (~209KB for 180×580×16bit). Current performance is acceptable for region changes.

### Station Count & Next-City Hopping

When pressing NEXT, the station cycles through stations at the current city, then hops to the next nearest city from the original touch point:

- `[Radio] Playing: Station Name (1/5)` → 5 stations available, currently on #1
- `[Radio] Playing: Station Name (5/5)` → Last station at this city
- `[Radio] -> Next city: Bratislava, SK` → Exhausted, auto-hopping to next nearest city
- `[Radio] Playing: Station Name (1/3)` → Now at the new city

The status bar shows `City, CC (idx/total)` — e.g., "Vienna, AT (2/5)". Up to 20 cities can be visited per touch session. Station cache holds up to 100 stations per city.

Many small cities have only 1 station in Radio.garden. NEXT will immediately hop to the next city.

---

## Future Features

### ✅ Completed Features

#### ~~1. Favorite Stations~~ → DONE (`favorites.cpp/h`)

- Menu → Favorites view with paginated list (6 per page, max 20)
- Tap left side to play, tap right "x" to delete
- ADD button saves currently playing station
- Stored as JSON on LittleFS (`/favorites.json`)
- Playing a favorite auto-switches to correct map slice + shows marker

#### 2. Playback History with Replay

Track recently played stations for quick replay:

- **History buffer**: Last 10-20 stations in RAM
- **UI access**: Touch gesture (swipe down?) or long-press combo
- **Serial command**: `H` to dump history, `H:3` to replay #3
- **Persistence**: Optional save to LittleFS on stop

#### 3. Enhanced Playback Info (LinkPlay getPlayerStatus)

Display more info from WiiM using `getPlayerStatus` API:

| Field | Description |
|-------|-------------|
| `Title` | Current track/stream title |
| `Artist` | Artist name (if available) |
| `Album` | Album name (if available) |
| `status` | play/pause/stop/loading |
| `vol` | Current volume (0-100) |
| `mute` | Mute state (0/1) |
| `mode` | Playback mode (see below) |
| `type` | Source type |

**Playback modes:**
- `10` = Network stream (HTTP)
- `31` = Spotify Connect
- `40` = Line In
- `41` = Bluetooth
- `43` = Optical
- `99` = DLNA/UPnP

**Implementation:**
```cpp
// Poll every 5 seconds when playing
String status = linkplay_get("/httpapi.asp?command=getPlayerStatus");
// Parse JSON: {"status":"play","vol":"50","Title":"Radio Wien",...}
```

#### ~~4. Volume Control~~ → DONE (`menu.cpp`, `linkplay_client.cpp`)

- Menu → Volume view with tap-based vertical slider (0-100%)
- Fetches current volume from WiiM on open
- Debounced LinkPlay API calls (200ms)

#### ~~5. Pause/Resume~~ → DONE (`menu.cpp`)

- Menu → Pause/Resume toggle
- Uses `setPlayerCmd:pause` / `setPlayerCmd:resume`

#### 6. Debug Log Display

Show serial-style logs on the ESP32 display:

- **Toggle**: Triple-tap or special button combo
- **Content**: Last N lines from Serial buffer
- **Use case**: Debugging without laptop connected
- **Implementation**: Ring buffer capturing Serial.printf() output

#### 7. Network Scan for WiiM Devices

Auto-discover WiiM devices on the network:

- **SSDP**: Search for `urn:schemas-upnp-org:device:MediaRenderer:1`
- **mDNS**: Look for `_linkplay._tcp` service
- **UI**: Show list of found devices on first boot / config menu
- **Storage**: Save selected device IP to NVS/LittleFS

```cpp
// SSDP discovery (simplified)
WiFiUDP udp;
udp.beginPacket("239.255.255.250", 1900);
udp.print("M-SEARCH * HTTP/1.1\r\n"
          "HOST: 239.255.255.250:1900\r\n"
          "MAN: \"ssdp:discover\"\r\n"
          "ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n");
udp.endPacket();
// Parse responses for WiiM devices
```

#### 8. Distance Display

Show how far you are from the current station's city:

- **Display**: "Vienna, AT (243 km)" in status bar
- **Calculation**: Haversine distance from touch point to city center
- **Update**: Recalculate on each new touch or city change
- **Implementation**: Already have lat/lon for both points

```cpp
// Haversine formula for distance between two points
float haversine_km(float lat1, float lon1, float lat2, float lon2) {
    const float R = 6371.0f;  // Earth radius in km
    float dlat = radians(lat2 - lat1);
    float dlon = radians(lon2 - lon1);
    float a = sin(dlat/2) * sin(dlat/2) +
              cos(radians(lat1)) * cos(radians(lat2)) *
              sin(dlon/2) * sin(dlon/2);
    float c = 2 * atan2(sqrt(a), sqrt(1-a));
    return R * c;
}

// Store touch coordinates for distance calculation
static float _touch_lat, _touch_lon;
```

#### ~~9. Dynamic Search (Next-City Hopping)~~ → DONE (`radio_client.cpp`, `places_db.cpp`)

- NEXT cycles through all stations at current city
- When exhausted, auto-hops to next nearest city from original touch point
- Uses `places_db_find_nearest_excluding()` with visited city list (max 20)
- Status bar updates with new city name and station count
- X marker moves to new city location

#### ~~10. Station Count Display~~ → DONE (`display.cpp`, `radio_client.cpp`)

- Status bar line 1: "City, CC (idx/total)" — e.g., "Vienna, AT (2/5)"
- Status bar line 2: Station name (truncated to 28 chars)
- `radio_get_station_index()` and `radio_get_total_stations()` accessors

#### ~~11. Display Layout~~ → DONE (`display.cpp`)

- Map: 180×580 full-width (no padding)
- Status bar: 3 lines — city+count, station name, [STOP][NEXT] buttons
- Text truncated with "..." at 28 chars

#### 12. Equalizer Control

WiiM supports built-in equalizer presets:

- **Presets**: off, classic, popular, jazzy, vocal
- **Serial**: `E:classic` or `E:0` (off), `E:1` (classic), etc.
- **API**: `setPlayerCmd:equalizer:<mode>`
- **UI**: Could add to long-press menu

```cpp
bool linkplay_set_equalizer(const char* mode) {
    // mode: "off", "classic", "popular", "jazzy", "vocal"
    String cmd = "setPlayerCmd:equalizer:" + String(mode);
    return make_request(cmd.c_str()).length() > 0;
}
```

#### ~~13. Sleep Timer~~ → DONE (`menu.cpp`, `linkplay_client.cpp`)

- Menu → Sleep Timer cycles through presets: Off/15/30/60/90 min
- Uses LinkPlay `setSleepTimer:<seconds>` API

### Planned Features (Short-term)

#### 14. WiiM Hardware Presets

Trigger WiiM's saved presets (configured via WiiM app):

- **Presets**: 1-6 hardware buttons on WiiM devices
- **Serial**: `PRESET:1` through `PRESET:6`
- **API**: `MCUKeyShortClick:<num>` (0-5 for presets 1-6)
- **Use case**: Quick access to favorite TuneIn/Spotify stations saved on WiiM

```cpp
bool linkplay_trigger_preset(int preset_num) {
    // preset_num: 1-6 (maps to MCU key 0-5)
    char cmd[32];
    snprintf(cmd, sizeof(cmd), "MCUKeyShortClick:%d", preset_num - 1);
    return make_request(cmd).length() > 0;
}
```

#### 15. Notification/Prompt Sounds

Play short audio notifications without interrupting main stream:

- **API**: `playPromptUrl:<url>`
- **Use case**: Play a "ding" sound when station changes
- **Note**: Requires hosting the sound file somewhere accessible

### Planned Features (Medium-term)

#### 16. Closeup Regional Maps

High-detail maps for radio-dense regions:

| Region | Coverage | Why |
|--------|----------|-----|
| Europe | -10° to 40° lon, 35° to 70° lat | Highest radio density |
| East Asia | 100° to 150° lon, 20° to 50° lat | Japan, Korea, China |
| Northeast US | -85° to -65° lon, 35° to 48° lat | Dense metro areas |

- **Gesture**: Double-tap on region to zoom in
- **Storage**: Additional bitmap per region (~5KB each)
- **Navigation**: Swipe to pan, button to zoom out

#### 17. Multiroom Support (LinkPlay)

Control multiple WiiM devices as a group:

- **API commands**:
  - `multiroom:getSlaveList` - Get paired speakers
  - `multiroom:SlaveKickout:<ip>` - Remove from group
  - `multiroom:SlaveVolume:<ip>:<vol>` - Per-speaker volume
- **UI**: Select which rooms to play to
- **Use case**: Whole-house radio

### Future Features (Long-term)

#### 18. UPnP/DLNA Streaming (Alternative to LinkPlay)

For non-WiiM speakers, implement standard UPnP:

```cpp
// SOAP request to SetAVTransportURI
String soap =
  "<?xml version=\"1.0\"?>"
  "<s:Envelope xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\">"
  "<s:Body><u:SetAVTransportURI xmlns:u=\"urn:schemas-upnp-org:service:AVTransport:1\">"
  "<InstanceID>0</InstanceID>"
  "<CurrentURI>" + stream_url + "</CurrentURI>"
  "</u:SetAVTransportURI></s:Body></s:Envelope>";
```

- **Benefit**: Works with any DLNA speaker
- **Complexity**: More verbose than LinkPlay, requires SSDP discovery
- **Priority**: Low (LinkPlay works great for WiiM)

#### 19. Bluetooth Audio Output

Play directly from ESP32 via Bluetooth A2DP:

- **Library**: ESP32-A2DP
- **Use case**: No WiFi speaker needed, use any BT speaker/headphones
- **Challenge**: ESP32 must decode audio stream (CPU intensive)
- **Alternative**: Some BT speakers accept URL via app - could send URL instead

#### 20. Web Configuration Interface

ESP32 hosts config webpage:

- **Features**: Set WiFi, WiiM IP, manage favorites, view history
- **Access**: `http://<esp32-ip>/`
- **Library**: ESPAsyncWebServer
- **Benefit**: No serial connection needed for setup

### LinkPlay API Reference

Common commands for WiiM/LinkPlay devices:

| Command | Description |
|---------|-------------|
| **Playback** | |
| `getPlayerStatus` | Current playback status, volume, track info (JSON) |
| `setPlayerCmd:play:<url>` | Play audio URL |
| `setPlayerCmd:pause` | Pause playback |
| `setPlayerCmd:resume` | Resume from pause |
| `setPlayerCmd:onepause` | Toggle pause/resume |
| `setPlayerCmd:stop` | Stop playback |
| `setPlayerCmd:prev` | Previous track |
| `setPlayerCmd:next` | Next track |
| `setPlayerCmd:seek:<pos>` | Seek to position (seconds) |
| **Volume & Audio** | |
| `setPlayerCmd:vol:<0-100>` | Set volume |
| `setPlayerCmd:mute:<0\|1>` | Mute/unmute |
| `setPlayerCmd:equalizer:<mode>` | EQ: off/classic/popular/jazzy/vocal |
| `getEqualizer` | Get current EQ mode |
| **Playback Modes** | |
| `setPlayerCmd:loopmode:<0-4>` | 0=sequence, 1=repeat-all, 2=repeat-one, 3=shuffle, 4=shuffle-repeat |
| `setPlayerCmd:switchmode:<mode>` | Change audio source |
| **Presets & Playlists** | |
| `MCUKeyShortClick:<0-5>` | Trigger preset 1-6 |
| `setPlayerCmd:playlist:<index>` | Play playlist by index |
| `playPromptUrl:<url>` | Play notification sound |
| **Timers** | |
| `setSleepTimer:<seconds>` | Set auto-shutoff timer |
| `getSleepTimer` | Get remaining sleep time |
| **Device Info** | |
| `getStatusEx` | Extended device status (JSON) |
| `getStatus` | Device info, firmware, SSID |
| `setDeviceName:<name>` | Rename device |
| `reboot` | Restart device |
| **Multiroom** | |
| `multiroom:getSlaveList` | List grouped speakers |
| `multiroom:SlaveKickout:<ip>` | Remove from group |
| `multiroom:SlaveVolume:<ip>:<vol>` | Per-speaker volume |
| `multiroom:SlaveMute:<ip>:<0\|1>` | Mute specific speaker |
| `multiroom:Ungroup` | Disband group |
| **USB/Local** | |
| `getLocalPlayList` | List USB/SD files |
| `setPlayerCmd:playLocalList:<idx>` | Play local file |

**Base URL**: `https://<wiim-ip>/httpapi.asp?command=<cmd>`

**Response format**: Plain text or JSON depending on command

**Sources**: [AndersFluur/LinkPlayApi](https://github.com/AndersFluur/LinkPlayApi), [Arylic HTTP API](https://developer.arylic.com/httpapi/)

---

## Feature Feasibility Analysis

> Analysis performed February 2026 based on codebase review and library research.

### Difficulty Legend

| Symbol | Effort | Description |
|--------|--------|-------------|
| 🟢 | Easy | Few hours to 1 day. Wraps existing APIs or minor changes. |
| 🟡 | Medium | 1-3 days. New module or significant refactoring with good library support. |
| 🟠 | Moderate-Hard | 3-7 days. Multiple new components or complex UI. |
| 🔴 | Hard | 1-2+ weeks. Missing libraries, architecture changes, or protocol implementation. |

### Feature Ratings

#### 🟢 Easy Features

| # | Feature | Lines | Why Easy |
|---|---------|-------|----------|
| 4 | Volume Control | ~20 | LinkPlay `setPlayerCmd:vol` already works. Add serial cmd + UI. |
| 5 | Pause/Resume | ~15 | Same as stop pattern. API: `setPlayerCmd:pause/resume`. |
| 10 | Station Count Display | ~10 | Data exists (`_current_station_index`). Update status bar to show "(2/5)". |
| 12 | Equalizer Control | ~25 | LinkPlay `setPlayerCmd:equalizer:classic`. Serial command wrapper. |
| 13 | Sleep Timer | ~20 | LinkPlay `setSleepTimer:<seconds>`. Simple wrapper. |
| 14 | WiiM Hardware Presets | ~15 | LinkPlay `MCUKeyShortClick:<0-5>`. Serial command `PRESET:1`. |
| 8 | Distance Display | ~30 | Haversine formula (documented above). Store touch coords, calculate on play. |

#### 🟡 Medium Features

| # | Feature | Lines | Notes |
|---|---------|-------|-------|
| 1 | Favorite Stations | ~150 | LittleFS + ArduinoJson pattern. New `favorites.cpp`, JSON read/write, gesture detection. |
| 2 | Playback History | ~100 | In-memory ring buffer. Optional LittleFS persistence. Similar to station cache. |
| 3 | Enhanced Playback Info | ~80 | `getPlayerStatus` returns JSON with Title/Artist/Album. Polling loop + display. |
| 7 | WiiM Auto-Discovery | ~100 | [ESPmDNS](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/protocols/mdns.html) built-in. [ESP32SSDP](https://github.com/luc-github/ESP32SSDP) available. Query `_linkplay._tcp`. |
| 9 | Dynamic Search | ~80 | Modify `places_db_find_nearest()` to return top 10 cities. Cycle cities when stations exhausted. |
| 15 | Notification Sounds | ~40 | LinkPlay `playPromptUrl:<url>`. Need hosted sound file or embedded web server. |
| 11 | Display Layout Overhaul | ~100 | Reduce map height, text truncation with `...`, show station count. Refactor `display.cpp`. |

#### 🟠 Moderate-Hard Features

| # | Feature | Lines | Notes |
|---|---------|-------|-------|
| 6 | Debug Log Display | ~200 | Ring buffer for Serial, redirect output, triple-tap toggle, overlay rendering. |
| 16 | Closeup Regional Maps | ~300 | New high-res bitmaps, zoom gestures, pan navigation. Python tooling updates. |
| 17 | Multiroom Support | ~250 | [LinkPlay multiroom API](https://developer.arylic.com/httpapi/) documented. Device discovery + selection UI. |
| 20 | Web Configuration UI | ~400 | [ESPAsyncWebServer](https://github.com/me-no-dev/ESPAsyncWebServer) + [ESPAsync_WiFiManager](https://github.com/khoih-prog/ESPAsync_WiFiManager). HTML/CSS/JS + captive portal. |

#### 🔴 Hard Features

| # | Feature | Lines | Why Hard |
|---|---------|-------|----------|
| 18 | UPnP/DLNA Streaming | ~500+ | No ESP32 library for *controlling* DLNA renderers. [SoapESP32](https://github.com/yellobyte/SoapESP32) only browses servers. Must implement SOAP/XML control protocol from scratch. |
| 19 | Bluetooth A2DP Output | ~1000+ | [ESP32-A2DP](https://github.com/pschatzmann/ESP32-A2DP) exists but ESP32 must decode audio streams (MP3/AAC). Need decoder library, significant memory, architecture change. Current design sends URLs to WiiM; BT requires ESP32 to fetch+decode+stream. |

### Implementation Priority Recommendations

**Quick wins (implement first):**
1. Volume Control (#4) + Pause/Resume (#5) - trivial, high value
2. Station Count Display (#10) - almost no code, better UX
3. Distance Display (#8) - fun feature, simple Haversine math

**Best ROI for medium effort:**
1. Favorites (#1) - users will want this
2. WiiM Auto-Discovery (#7) - removes hardcoded IP friction
3. Dynamic Search (#9) - makes NEXT button much more useful

**Consider dropping or deferring:**
- UPnP/DLNA (#18) - LinkPlay works well, not worth the protocol complexity
- Bluetooth A2DP (#19) - fundamentally different architecture, would be a separate project

### Key Infrastructure Notes

**What already exists (reusable):**
- LinkPlay client with HTTPS, URL encoding, retry logic (`linkplay_client.cpp`)
- LittleFS with 4MB partition (only 634KB used for places.bin)
- ArduinoJson for parsing (16KB DynamicJsonDocument)
- Serial command infrastructure with `peek()` pattern
- Station caching with index cycling
- PSRAM support for large allocations

**Libraries to add for specific features:**
- mDNS: Built-in `ESPmDNS.h` (no install needed)
- SSDP: [ESP32SSDP](https://github.com/luc-github/ESP32SSDP) via PlatformIO
- Web server: [ESPAsyncWebServer](https://github.com/me-no-dev/ESPAsyncWebServer) + AsyncTCP
- Bluetooth: [ESP32-A2DP](https://github.com/pschatzmann/ESP32-A2DP) (if pursuing #19)
