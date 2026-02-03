# RadioWall 🗺️📻

An interactive world map that plays local radio stations when you touch a location. Touch Vienna, hear Austrian radio. Touch Tokyo, hear Japanese radio.

## The Vision

A framed **physical world map** (paper or cloth) with an **invisible capacitive touch layer**. No glowing screens on the map itself — just a beautiful analog map you can touch to explore the world's radio stations.

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Picture Frame                                │
│   ┌────────────────────────────────────────────────────────────┐     │
│   │                                                            │     │
│   │         Physical Paper/Cloth World Map                     │     │
│   │              (equirectangular projection)                  │     │
│   │                                                            │     │
│   │                    + Touch Panel Overlay                   │     │
│   │                                                            │     │
│   └────────────────────────────────────────────────────────────┘     │
│                              │ USB                                    │
│   ┌────────────────────────────────────────────────────────────┐     │
│   │  Touch Controller ──► ESP32-S3-Long ◄── 5V Power           │     │
│   │                    ┌─────────────────┐                     │     │
│   │                    │  Now Playing:   │                     │     │
│   │                    │  Radio Wien     │  ← Small status     │     │
│   │                    │  Vienna, AT     │    display only     │     │
│   │                    └─────────────────┘                     │     │
│   └────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
                              │ WiFi (standalone - no server!)
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
    ┌─────────────────┐             ┌─────────────────┐
    │  Radio.garden   │             │   WiiM Speaker  │
    │  (stations API) │             │  (LinkPlay API) │
    └─────────────────┘             └─────────────────┘
```

---

## Current State: Standalone Mode ✅

> **Fully working!** ESP32 operates completely standalone — no server required. Touch map → find city → fetch Radio.garden stations → play on WiiM.

### What Works Now

- ✅ **Standalone Operation**: No server needed! ESP32 does everything directly
- ✅ **Places Database**: 12,486 cities loaded from LittleFS (~634KB)
- ✅ **Radio.garden Client**: HTTPS API, JSON parsing, station caching
- ✅ **LinkPlay Client**: WiiM control via HTTPS (port 443)
- ✅ **Multi-Action Button**: Short press (region), long press (stop), double-tap (next)
- ✅ **Touch Controls**: Map touch, STOP/NEXT buttons in status bar
- ✅ **Optimized Rendering**: drawFastHLine for faster map display (~4s)

### What's Next

- 📦 **Waiting for**: USB-C OTG adapter + breakout board (ordered)
- 🔧 **TODO**: USB Host HID for external 9" touch panel
- 🔧 **TODO**: Display layout improvements (text wrapping fixes)
- 🎯 **Final**: Large PCAP touch foil (55"+), physical map, custom frame

---

## Quick Start

### 1. Server (Docker)

```bash
git clone https://github.com/Swoop0717/RadioWall.git
cd RadioWall

cp server/config.example.yaml server/config.yaml
# Edit config.yaml if needed (defaults work for local setup)

docker compose up -d
docker compose logs -f
```

### 2. Test Without Hardware

```bash
# Simulate touch on Vienna, Austria
docker exec radiowall-mosquitto-1 mosquitto_pub \
  -t "radiowall/touch" -m '{"x":558,"y":193}'

# Commands
docker exec radiowall-mosquitto-1 mosquitto_pub \
  -t "radiowall/command" -m '{"cmd":"next"}'

docker exec radiowall-mosquitto-1 mosquitto_pub \
  -t "radiowall/command" -m '{"cmd":"stop"}'
```

### 3. ESP32 Firmware (PlatformIO)

```bash
cd esp32
cp src/config.example.h src/config.h
# Edit config.h: WiFi credentials, MQTT server IP

pio run -t upload
pio device monitor
```

---

## Hardware

### Current Development Setup

| Component | Model | Status |
|-----------|-------|--------|
| ESP32 | LILYGO T-Display-S3-Long (3.4" AMOLED) | ✅ Working |
| Touch Panel | 9" Capacitive (XY-PG9020) + USB controller | ✅ Have, untested with ESP32 |
| Server | N100 mini PC (Docker) | ✅ Running |
| Speaker | WiiM Amp Pro (UPnP/DLNA) | ✅ Working |
| USB-C OTG adapter | USB-A F → USB-C M | 📦 Ordered |
| USB-C breakout | Power ESP32 via 5V pin | 📦 Ordered |
| LiPo Battery | 3000mAh 3.7V, JST 1.25mm | 📦 Ordered |

### Target Production Setup (55"+)

- **PCAP Touch Foil**: Large format capacitive film (32"–180"+)
- **Physical Map**: Equirectangular projection print (NASA Blue Marble, Natural Earth, etc.)
- **Frame**: Custom frame with glass front
- **ESP32**: Hidden in frame, showing only "Now Playing" on small display

---

## Development Roadmap

### ✅ Phase 1: Server (Complete)
- [x] Docker Compose deployment (Mosquitto + Python server)
- [x] Radio.garden API client with place caching
- [x] Stream validation (skip dead streams)
- [x] UPnP/DLNA playback to WiiM
- [x] MQTT handler with stop/next/replay commands
- [x] Coordinate conversion (pixel → lat/lon)

### ✅ Phase 2: Prototype 1 - Built-in Touch (Complete)
- [x] ESP32 display driver (Arduino_GFX + AXS15231)
- [x] Built-in touchscreen (I2C interrupt-driven)
- [x] WiFi + MQTT client with auto-reconnect
- [x] World map rendering (RLE-compressed coastlines)
- [x] 4 longitude slices with button cycling
- [x] Zone-based touch (map area vs status bar)
- [x] End-to-end flow working

### ✅ Phase 3: Standalone Mode (Complete - No Server!)
- [x] Places database compiler (12,486 cities → 634KB LittleFS)
- [x] ESP32 Radio.garden API client (`radio_client.cpp`)
- [x] LinkPlay client for WiiM (`linkplay_client.cpp`) — simpler than UPnP!
- [x] Direct touch → lookup → play flow (no MQTT needed)
- [x] Multi-action button (short/long/double-tap)
- [x] Optimized map rendering with drawFastHLine

### 🔧 Phase 4: Prototype 2 (External Touch Panel)
- [ ] USB-C OTG adapter testing
- [ ] USB Host HID implementation for touch panel
- [ ] Calibration tool (touch corners → save config)
- [ ] Test with 9" touch panel over physical map printout
- [ ] Simplify ESP32 display to "Now Playing" only

### ⬜ Phase 5: Production
- [ ] Large PCAP touch foil (55"+)
- [ ] High-quality equirectangular map print
- [ ] Frame design and construction
- [ ] Power solution (wall adapter or battery)
- [ ] Final installation

---

## Future Features

### Short-term (Software improvements)

| Feature | Description |
|---------|-------------|
| **Favorites** | Save/export favorite stations to LittleFS |
| **History** | Track recently played stations with replay |
| **Distance Display** | Show "Vienna (243 km)" - distance to current city |
| **Dynamic Search** | Auto-jump to next nearest city when stations exhausted |
| **Station Count** | Show "(2/5)" progress on display |
| **Display Overhaul** | Fix text wrapping, better layout |
| **Volume Control** | Adjust WiiM volume via touch/serial |
| **Pause/Resume** | Toggle playback without stopping |
| **Equalizer** | WiiM EQ presets (classic, jazz, vocal, etc.) |
| **Sleep Timer** | Auto-stop after X minutes |
| **WiiM Presets** | Trigger saved TuneIn/Spotify presets |
| **Device Discovery** | Auto-find WiiM on network (SSDP/mDNS) |
| **Debug Display** | Show serial logs on screen |

### Medium-term

| Feature | Description |
|---------|-------------|
| **Regional Zoom** | High-detail maps for Europe, East Asia, NE US |
| **Multiroom** | Control multiple WiiM speakers as group |
| **Web Config** | ESP32-hosted config page (no serial needed) |

### Long-term

| Feature | Description |
|---------|-------------|
| **UPnP/DLNA** | Support non-WiiM speakers |
| **Bluetooth** | Direct BT audio output from ESP32 |

See [CLAUDE.md](CLAUDE.md) for detailed implementation notes on each feature.

---

## Architecture: Standalone ESP32 ✅

**Implemented!** No server required — just ESP32 + WiiM + WiFi:

```
┌─────────────────────────────────────────────────────────────┐
│                      Picture Frame                           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │     Physical Map + Capacitive Touch Panel             │  │
│  └───────────────────────────────────────────────────────┘  │
│                            │ USB                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                     ESP32-S3                          │  │
│  │                                                       │  │
│  │  1. Touch → lat/lon                                   │  │
│  │  2. Lookup nearest city (12,486 in LittleFS)          │  │
│  │  3. Fetch stations from Radio.garden API              │  │
│  │  4. Send stream URL to WiiM via LinkPlay HTTPS        │  │
│  │                                                       │  │
│  │                 ┌─────────────────┐                   │  │
│  │                 │  Now Playing    │                   │  │
│  │                 └─────────────────┘                   │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │ WiFi
                            ▼
        ┌───────────────────────────────────────┐
        │              Home WiFi                │
        │                                       │
        │   ┌───────────┐       ┌───────────┐  │
        │   │  WiiM     │◄──────│  Radio    │  │
        │   │  Mini 🔊  │ stream│  .garden  │  │
        │   └───────────┘       └───────────┘  │
        └───────────────────────────────────────┘
```

**How it works:**
1. ESP32 has 12,486 Radio.garden places in LittleFS (~634KB)
2. Touch → find nearest city → fetch stations from Radio.garden API
3. ESP32 sends stream URL to WiiM via **LinkPlay HTTPS API** (simpler than UPnP!)
4. WiiM fetches and plays the stream directly from the internet

**Key files:**
| File | Purpose |
|------|---------|
| `tools/compile_places.py` | Download places → `places.bin` |
| `esp32/src/places_db.cpp` | Load places, nearest-city lookup |
| `esp32/src/radio_client.cpp` | Radio.garden API client |
| `esp32/src/linkplay_client.cpp` | WiiM control via LinkPlay HTTPS |

---

## Prototype 1: ESP32 Display UI

> This is temporary — in the final version, the map is physical and the ESP32 just shows "Now Playing".

The T-Display-S3-Long shows a **portrait** world map (180×640 pixels):

```
┌──────────────────┐
│ ┌──────────────┐ │  ← Map area (160×560)
│ │              │ │    RLE-compressed coastlines
│ │  World Map   │ │    Touch to select location
│ │  (current    │ │
│ │   slice)     │ │
│ │              │ │
│ └──────────────┘ │
│                  │
│ Region: Europe   │  ← Status bar (60px)
│ Radio Wien|Vienna│    Shows current station
│ [STOP]    [NEXT] │    Touch buttons
└──────────────────┘
```

### Longitude Slices

Press **Button 1** (GPIO 0) to cycle through 4 world regions:

| Slice | Longitude Range | Includes |
|-------|-----------------|----------|
| Americas | -150° to -30° | North/South America |
| Europe/Africa | -30° to 60° | Europe, Africa, Middle East |
| Asia | 60° to 150° | Russia, India, China, Japan |
| Pacific | 150° to -150° | Australia, Pacific Islands |

---

## MQTT Protocol

### Topics

| Topic | Direction | Payload |
|-------|-----------|---------|
| `radiowall/touch` | ESP32 → Server | `{"x": 512, "y": 300, "ts": 1234567890}` |
| `radiowall/nowplaying` | Server → ESP32 | `{"station": "Radio Wien", "location": "Vienna", "country": "AT"}` |
| `radiowall/status` | Server → ESP32 | `{"state": "playing"}` / `"stopped"` / `"loading"` / `"error"` |
| `radiowall/command` | ESP32 → Server | `{"cmd": "stop"}` / `"next"` / `"replay"}` |

### Stream Selection Flow

1. Touch event received with (x, y) pixel coordinates
2. Server converts to lat/lon (equirectangular projection)
3. Finds ~20 nearest stations via Radio.garden API
4. Validates each stream (HEAD request + read first chunk)
5. Sends first working stream to UPnP speaker
6. `next` command continues through the list

---

## Project Structure

```
RadioWall/
├── docker-compose.yml
├── mosquitto/
│   └── mosquitto.conf
├── server/
│   ├── Dockerfile
│   ├── main.py              # Orchestration
│   ├── radio_garden.py      # API client + stream validation
│   ├── coordinates.py       # Pixel → lat/lon conversion
│   ├── upnp_streamer.py     # UPnP/DLNA control
│   ├── mqtt_handler.py      # MQTT pub/sub
│   └── config.example.yaml
├── esp32/
│   ├── platformio.ini
│   ├── lib/                 # Arduino_GFX, Arduino_DriveBus
│   └── src/
│       ├── main.cpp
│       ├── display.cpp/h    # AMOLED rendering
│       ├── builtin_touch.cpp/h  # Built-in touch (Prototype 1)
│       ├── usb_touch.cpp/h  # USB touch panel (Prototype 2)
│       ├── mqtt_client.cpp/h
│       ├── ui_state.cpp/h   # Slice/playback state
│       ├── world_map.cpp/h  # RLE bitmap rendering
│       ├── button_handler.cpp/h
│       └── pins_config.h
├── tools/
│   ├── generate_map_bitmaps.py  # Generate coastline data
│   └── requirements.txt
└── docs/
    ├── hardware_testing.md
    └── world_map_implementation.md
```

---

## Configuration

### Server (`server/config.yaml`)

```yaml
mqtt:
  host: "localhost"
  port: 1883

radio_garden:
  n_stations: 20
  selection_mode: "random"  # or "nearest", "popular"

calibration:
  touch_max_x: 1024
  touch_max_y: 600

upnp:
  device_name: null  # Auto-discover first renderer
```

### ESP32 (`esp32/src/config.h`)

```cpp
#define WIFI_SSID "your_wifi"
#define WIFI_PASSWORD "your_password"
#define MQTT_SERVER "192.168.1.100"
#define MQTT_PORT 1883

// Toggle between built-in touch (Prototype 1) and USB touch (Prototype 2)
#define USE_BUILTIN_TOUCH 1
```

---

## Hardware Resources

- **Touch Panels**: [Pro Display PCAP Foils](https://prodisplay.com/touch-screens/interactive-overlays/pcap-touch-foil/), [Keetouch](https://keetouch.eu/), AliExpress
- **Maps**: [NASA Blue Marble](https://visibleearth.nasa.gov/collection/1484/blue-marble), [Natural Earth](https://www.naturalearthdata.com/)
- **LiPo Batteries**: JST 1.25mm 2-pin, 3.7V, 2000-3500mAh

---

## License

MIT

## Contributing

PRs welcome! See [CLAUDE.md](CLAUDE.md) for detailed technical context.
