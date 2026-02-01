# RadioWall 🗺️📻

An interactive world map that plays local radio stations when you touch a location. Touch Vienna, hear Austrian radio. Touch Tokyo, hear Japanese radio. No screen, no glowing display — just a beautiful physical map behind invisible touch-sensing glass.

## The Vision

A framed physical world map (paper or cloth) with a transparent capacitive touch layer. Touch anywhere on the map, and an ESP32 sends coordinates to your home server, which finds the nearest radio stations and streams them to your speakers.

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Picture Frame                                │
│                                                                       │
│   ┌────────────────────────────────────────────────────────────┐     │
│   │                                                            │     │
│   │         Physical Paper/Cloth World Map                     │     │
│   │              (equirectangular projection)                  │     │
│   │                                                            │     │
│   │                    + Touch Panel Overlay                   │     │
│   │                                                            │     │
│   └────────────────────────────────────────────────────────────┘     │
│                              │ USB                                    │
│                              ▼                                        │
│   ┌────────────────────────────────────────────────────────────┐     │
│   │                                                            │     │
│   │  Touch Controller ──► ESP32-S3-Long ◄── 5V Power           │     │
│   │       (USB)              │    │         (via pins)         │     │
│   │                          │    │                            │     │
│   │                    ┌─────┴────┴─────┐                      │     │
│   │                    │  Now Playing:  │                      │     │
│   │                    │  Radio Wien    │                      │     │
│   │                    │  Vienna, AT    │                      │     │
│   │                    └────────────────┘                      │     │
│   │                                                            │     │
│   └────────────────────────────────────────────────────────────┘     │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
                              │ WiFi / MQTT
                              ▼
                    ┌─────────────────┐
                    │   Home Server   │
                    │   (Docker)      │
                    │                 │
                    │ - Mosquitto     │
                    │ - Radio.garden  │
                    │ - UPnP control  │
                    └─────────────────┘
                              │ UPnP / DLNA
                              ▼
                    ┌─────────────────┐
                    │   WiiM Amp Pro  │
                    │       🔊        │
                    └─────────────────┘
```

## Quick Start

### Server (Docker)

The server runs via Docker Compose — no host packages needed.

```bash
git clone https://github.com/Swoop0717/RadioWall.git
cd RadioWall

# Create config
cp server/config.example.yaml server/config.yaml
# Edit server/config.yaml if needed (defaults work for local setup)

# Start
docker compose up -d

# Check logs
docker compose logs -f
```

### Test it

```bash
# Simulate a touch on Seoul, South Korea
docker exec radiowall-mosquitto-1 mosquitto_pub -t "radiowall/touch" -m '{"x":873,"y":175}'

# Skip to next station
docker exec radiowall-mosquitto-1 mosquitto_pub -t "radiowall/command" -m '{"cmd":"next"}'

# Stop playback
docker exec radiowall-mosquitto-1 mosquitto_pub -t "radiowall/command" -m '{"cmd":"stop"}'
```

### ESP32 Firmware (PlatformIO)

```bash
cd esp32
cp src/config.example.h src/config.h
# Edit src/config.h with WiFi credentials and MQTT server IP

pio run -t upload        # Build and flash
pio device monitor       # Serial monitor
```

---

## MQTT Protocol

### Topics

| Topic | Direction | Payload |
|-------|-----------|---------|
| `radiowall/touch` | ESP32 → Server | `{"x": 512, "y": 300, "ts": 1234567890}` |
| `radiowall/nowplaying` | Server → ESP32 | `{"station": "Radio Wien", "location": "Vienna, Austria", "country": "AT"}` |
| `radiowall/status` | Server → ESP32 | `{"state": "playing"}` or `{"state": "stopped"}` or `{"state": "loading"}` or `{"state": "error", "msg": "..."}` |
| `radiowall/command` | ESP32 → Server | `{"cmd": "stop"}` or `{"cmd": "next"}` or `{"cmd": "replay"}` |

### Commands

| Command | Description |
|---------|-------------|
| `stop` | Stop playback on the speaker |
| `next` | Skip to the next station in the same area (skips dead streams) |
| `replay` | Re-touch the same location (fresh random selection from nearby stations) |

### Stream Selection

When a touch event is received, the server:
1. Converts pixel coordinates to lat/long
2. Finds the ~20 nearest radio stations via Radio.garden
3. Shuffles them (in `random` mode) or orders by distance/popularity
4. Tries each station in order, checking if the stream is alive
5. Sends the first working stream to the UPnP speaker
6. The `next` command continues from where it left off in the list

---

## Hardware

### Current Development Setup
| Component | Model | Purpose |
|-----------|-------|---------|
| Touch Panel | 9" Capacitive (XY-PG9020) | Touch input for map |
| USB Controller | Included with panel | Converts touch to USB HID |
| ESP32 | LILYGO T-Display-S3-Long | Touch processing + "Now Playing" display |
| Server | Any Linux box with Docker | API + streaming (N100, Raspberry Pi, etc.) |
| Speaker | WiiM Amp Pro | Audio output via UPnP/DLNA |

### Required Adapters (Ordered)
| Item | Purpose |
|------|---------|
| USB-C OTG adapter (USB-A F → USB-C M) | Connect touch USB to ESP32 |
| USB-C breakout board | Power ESP32 via 5V pin while USB-C used for touch |

### Target Production Setup (55"+)
- **PCAP Touch Foil**: Large format capacitive touch film (32"–180"+)
- **Physical Map**: Equirectangular projection print
- **Frame**: Custom frame with glass front
- **LiPo Battery**: For cordless operation (2000-3500mAh recommended)

---

## Server Configuration

Copy `server/config.example.yaml` to `server/config.yaml`:

```yaml
# MQTT Broker
mqtt:
  host: "localhost"          # Use "localhost" with Docker host networking
  port: 1883

# Radio.garden API
radio_garden:
  n_stations: 20             # How many nearby stations to consider
  selection_mode: "random"   # "random", "nearest", or "popular"

# Touch panel calibration
calibration:
  touch_min_x: 0
  touch_max_x: 1024         # Verify with your panel
  touch_min_y: 0
  touch_max_y: 600           # Verify with your panel
  map_north: 90              # Adjust if map is cropped
  map_south: -90
  map_west: -180
  map_east: 180

# UPnP/DLNA Speaker
upnp:
  device_name: null          # null = auto-discover first renderer
  discovery_timeout: 5
  default_volume: null       # null = leave unchanged
```

---

## Radio.garden API

Unofficial API (no auth required):

```bash
# Get all places with radio stations (~12,500 places)
curl http://radio.garden/api/ara/content/places

# Response: {"data": {"list": [
#   {"id": "IgQ9XxkV", "title": "Vienna", "country": "Austria",
#    "geo": [16.37, 48.21], "size": 102},  # Note: [longitude, latitude]!
# ]}}

# Get stations at a place
curl http://radio.garden/api/ara/content/page/{place_id}/channels

# Stream a station (redirects to actual stream)
curl -L http://radio.garden/api/ara/content/listen/{station_id}/channel.mp3
```

**Important**: The `geo` field is `[longitude, latitude]` (not lat/long!)

---

## Coordinate Conversion

The map uses equirectangular projection (Plate Carrée). Conversion from touch pixels to geographic coordinates is linear:

```python
longitude = (x / touch_width) * 360 - 180   # -180 to +180
latitude = 90 - (y / touch_height) * 180    # +90 to -90
```

Touch resolution is determined by the panel's controller chip, not its physical size. A 9" and 55" panel with the same controller report the same coordinate range. Calibrate by touching corners and reading raw values with `evtest` or the ESP32 serial output.

---

## Project Structure

```
RadioWall/
├── docker-compose.yml          # Docker Compose (Mosquitto + server)
├── .dockerignore
├── mosquitto/
│   └── mosquitto.conf          # MQTT broker config
├── server/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.example.yaml     # Configuration template
│   ├── main.py                 # Orchestration + command handling
│   ├── radio_garden.py         # Radio.garden API client + stream validation
│   ├── coordinates.py          # Pixel → lat/long conversion
│   ├── upnp_streamer.py        # UPnP/DLNA speaker discovery + playback
│   └── mqtt_handler.py         # MQTT pub/sub
├── esp32/
│   ├── platformio.ini          # PlatformIO build config
│   └── src/
│       ├── config.example.h    # WiFi/MQTT config template
│       ├── main.cpp            # Entry point
│       ├── usb_touch.cpp/.h    # USB Host HID touch reading
│       ├── mqtt_client.cpp/.h  # WiFi + MQTT client
│       └── display.cpp/.h      # AMOLED display UI
├── docs/
│   └── hardware_testing.md     # Hardware verification guide
└── playground.ipynb            # Original prototype (reference)
```

---

## Development Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0: Hardware Testing | 🟡 Partial | Touch panel verified on PC, WiiM discovered |
| Phase 1: Server | ✅ Done | Docker deployment, Radio.garden API, UPnP streaming, MQTT, stream validation, next/stop/replay commands |
| Phase 2: ESP32 Firmware | 🔧 Skeleton | Code written, needs hardware testing + USB Host HID |
| Phase 3: Integration | ⬜ Not started | End-to-end testing, calibration tool |
| Phase 4: Production | ⬜ Not started | Large touch foil, frame, final installation |

---

## Power Consumption

| Component | Active | Idle (display dimmed) |
|-----------|--------|----------------------|
| ESP32-S3 (WiFi, modem sleep) | ~80-120mA | ~20-50mA |
| AMOLED Display | ~20-40mA | ~5mA |
| Touch USB Controller | ~10-20mA | ~10mA |
| **Total** | **~110-180mA** | **~35-65mA** |

With a 2000-3500mAh LiPo: ~1-4 days cordless operation.

---

## Hardware Resources

- **Touch Panels**: [Pro Display PCAP Foils](https://prodisplay.com/touch-screens/interactive-overlays/pcap-touch-foil/) (UK), [Keetouch](https://keetouch.eu/) (EU), AliExpress "capacitive touch panel USB" (budget)
- **Maps**: [NASA Blue Marble](https://visibleearth.nasa.gov/collection/1484/blue-marble), [Natural Earth](https://www.naturalearthdata.com/)
- **LiPo Batteries**: JST 1.25mm 2-pin, 3.7V, 2000-3500mAh (**do not exceed 4.2V!**)

---

## License

MIT

## Contributing

PRs welcome! Check the Development Status table above for what needs work.
