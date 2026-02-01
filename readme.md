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
│   │                    │  Radio Wien 📻 │                      │     │
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
                    │   (N100/Pi)     │
                    │                 │
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

## Hardware

### Current Development Setup
| Component | Model | Purpose |
|-----------|-------|---------|
| Touch Panel | 9" Capacitive (XY-PG9020) | Touch input for map |
| USB Controller | Included with panel | Converts touch to USB HID |
| ESP32 | LILYGO T-Display-S3-Long | Touch processing + "Now Playing" display |
| Dev Server | Desktop PC / Raspberry Pi 3B+ | API + streaming during development |
| Speaker | WiiM Amp Pro | Audio output via UPnP |

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

## Power Consumption

### Estimated Current Draw
| Component | Active | Idle (display dimmed) |
|-----------|--------|----------------------|
| ESP32-S3 (WiFi, modem sleep) | ~80-120mA | ~20-50mA |
| AMOLED Display | ~20-40mA | ~5mA |
| Touch USB Controller | ~10-20mA | ~10mA |
| **Total** | **~110-180mA** | **~35-65mA** |

### Battery Life Estimates
| Battery Capacity | Active Use | Mostly Idle |
|------------------|------------|-------------|
| 1000mAh | ~6-9 hours | ~15-28 hours |
| 2000mAh | ~12-18 hours | ~1-2 days |
| 3500mAh | ~20-32 hours | ~2-4 days |

**Recommendation**: 2000-3500mAh LiPo for 1-4 days cordless operation.

---

## Development Plan

### Phase 0: Hardware Verification ⏳
*Goal: Confirm all hardware works before writing code*

**On Desktop PC:**
- [ ] Assemble touch panel + USB controller
- [ ] Plug into PC, verify it appears as HID device
- [ ] Test touch → cursor movement works
- [ ] Note the touch resolution/coordinate range

**On Raspberry Pi 3B+:**
- [ ] Flash Raspberry Pi OS Lite
- [ ] Connect touch panel via USB
- [ ] Verify touch events with `evtest` or `libinput debug-events`
- [ ] Test audio output (HDMI/aux or UPnP to WiiM)

**On ESP32-S3-Long (once adapters arrive):**
- [ ] Flash test firmware, verify display works
- [ ] Test USB Host mode with touch panel
- [ ] Verify WiFi connectivity

---

### Phase 1: Server Application 🖥️
*Goal: Working radio selection + streaming on server*

**Develop on Desktop, deploy to Pi/N100**

```
server/
├── radio_garden.py      # API client
├── coordinates.py       # X/Y → Lat/Long conversion  
├── upnp_streamer.py     # UPnP/DLNA control
├── mqtt_handler.py      # Receive touch events from ESP32
├── main.py              # Orchestration
└── config.yaml          # Settings
```

**Tasks:**
- [ ] Radio.garden API client (fetch places, find nearest, get stream URL)
- [ ] Coordinate conversion (pixel → lat/long, with calibration)
- [ ] UPnP discovery and playback control for WiiM
- [ ] MQTT broker setup (can use Mosquitto)
- [ ] MQTT listener for touch events
- [ ] Integration: touch event → find station → play on WiiM

**Test without ESP32:**
```bash
# Simulate touch event
mosquitto_pub -t "radiowall/touch" -m '{"x": 500, "y": 300}'
# Should trigger radio playback on WiiM
```

---

### Phase 2: ESP32 Firmware 📟
*Goal: ESP32 reads touch, sends to server, shows "Now Playing"*

```
esp32/
├── src/
│   ├── main.cpp
│   ├── usb_host.cpp      # Read USB HID touch events
│   ├── wifi_manager.cpp  # WiFi connection
│   ├── mqtt_client.cpp   # Send touch, receive now-playing
│   └── display.cpp       # Show station info on AMOLED
├── platformio.ini
└── config.h
```

**Tasks:**
- [ ] USB Host mode setup for touch panel
- [ ] Parse HID touch reports → X/Y coordinates
- [ ] WiFi connection with reconnection logic
- [ ] MQTT client: publish touch events
- [ ] MQTT client: subscribe to now-playing updates
- [ ] Display: show station name, location, maybe album art?
- [ ] Power management: dim display when idle

**MQTT Topics:**
```
radiowall/touch        → ESP32 publishes: {"x": 500, "y": 300}
radiowall/nowplaying   → Server publishes: {"station": "Radio Wien", "location": "Vienna, Austria"}
radiowall/status       → Server publishes: {"state": "playing"} or {"state": "stopped"}
```

---

### Phase 3: Integration & Calibration 🔧
*Goal: Everything works together*

- [ ] Calibration tool: touch corners of map, calculate transform
- [ ] Save calibration to ESP32 flash / server config
- [ ] Handle edge cases: ocean touches, no stations nearby
- [ ] Error handling: WiFi disconnect, server offline, stream fails

---

### Phase 4: Production Hardware 🖼️
*Goal: Beautiful wall-mounted installation*

- [ ] Source/print large equirectangular map
- [ ] Order appropriately sized PCAP touch foil
- [ ] Design and build frame
- [ ] Integrate all electronics
- [ ] Final calibration
- [ ] Add LiPo battery + charging circuit

---

### Phase 5: Polish ✨
*Goal: Nice-to-have features*

- [ ] Multiple station selection (when many nearby)
- [ ] Volume control via touch gesture (swipe up/down?)
- [ ] Visual feedback: LED strip around frame?
- [ ] Sleep mode: turn off after X minutes idle
- [ ] Web dashboard for configuration
- [ ] OTA updates for ESP32

---

## Software Architecture

### Communication Flow
```
┌─────────────┐     MQTT: radiowall/touch      ┌─────────────┐
│   ESP32     │ ────────────────────────────►  │   Server    │
│             │                                │             │
│  USB Touch  │     MQTT: radiowall/nowplaying │ Radio.garden│
│  Display    │ ◄──────────────────────────────│ UPnP Control│
└─────────────┘                                └─────────────┘
                                                      │
                                                      │ UPnP
                                                      ▼
                                               ┌─────────────┐
                                               │  WiiM Amp   │
                                               └─────────────┘
```

### Why This Split?
- **ESP32**: Fast touch response, low power, small form factor, built-in display
- **Server**: Heavy lifting (API calls, UPnP), always-on, easy to update
- **MQTT**: Lightweight, real-time, perfect for IoT

---

## Radio.garden API

Radio.garden doesn't have an official public API, but these endpoints work:

```bash
# Get all places with radio stations
curl http://radio.garden/api/ara/content/places

# Response format:
# { "data": { "list": [
#   { "id": "...", "title": "Vienna", "country": "Austria", 
#     "geo": [16.37, 48.21], "size": 42 },  # Note: [longitude, latitude]!
# ]}}

# Get stations at a place
curl http://radio.garden/api/ara/content/page/{place_id}/channels

# Stream a station (redirects to actual stream)
curl -L http://radio.garden/api/ara/content/listen/{station_id}/channel.mp3
```

**Important**: The `geo` field is `[longitude, latitude]` (not lat/long!)

---

## Coordinate Conversion

### Equirectangular Projection (Plate Carrée)

For a standard world map, conversion from pixel to geographic coordinates is linear:

```python
def pixel_to_latlong(x, y, width, height):
    """Convert pixel coordinates to latitude/longitude.
    
    Assumes full world map: -180 to +180 longitude, +90 to -90 latitude
    """
    longitude = (x / width) * 360 - 180    # -180 to +180
    latitude = 90 - (y / height) * 180     # +90 to -90
    return latitude, longitude
```

### Calibration

Real installations need calibration for:
- Touch area offset from map edges
- Non-standard map bounds (cropped maps)
- Rotation if mounted at an angle

```yaml
# config.yaml
calibration:
  # Touch panel reports coordinates in this range
  touch_min_x: 0
  touch_max_x: 1024
  touch_min_y: 0
  touch_max_y: 600
  
  # Map bounds in geographic coordinates
  map_north: 90
  map_south: -90
  map_west: -180
  map_east: 180
```

---

## Development Environment Setup

### Server (Python)
```bash
# Clone repo
git clone https://github.com/Swoop0717/RadioWall.git
cd RadioWall

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Run server
python -m server.main
```

### ESP32 (PlatformIO)
```bash
# Install PlatformIO CLI or use VS Code extension
cd esp32

# Build and upload
pio run -t upload

# Monitor serial output
pio device monitor
```

### MQTT Broker (Mosquitto)
```bash
# Install on server (Debian/Ubuntu)
sudo apt install mosquitto mosquitto-clients

# Test
mosquitto_sub -t "radiowall/#" -v  # Subscribe to all topics
mosquitto_pub -t "radiowall/touch" -m '{"x":100,"y":200}'  # Publish test
```

---

## Hardware Resources

### Touch Panels & Foils
- [Pro Display PCAP Foils](https://prodisplay.com/touch-screens/interactive-overlays/pcap-touch-foil/) (UK, premium)
- [Keetouch](https://keetouch.eu/) (EU)
- AliExpress: Search "capacitive touch panel USB" (budget)

### Maps (Equirectangular)
- [NASA Blue Marble](https://visibleearth.nasa.gov/collection/1484/blue-marble)
- [Natural Earth](https://www.naturalearthdata.com/)

### LiPo Batteries
- JST 1.25mm 2-pin connector (matches T-Display-S3-Long)
- 3.7V, 2000-3500mAh recommended
- **Do not exceed 4.2V!**

---

## Project History

This project started as a Python prototype using VLC and matplotlib (see `playground.ipynb`). The current architecture evolved to be headless and energy-efficient for permanent wall installation.

Key decisions:
- **No display on map** → Physical map is more beautiful and energy-efficient
- **ESP32 over Raspberry Pi** → Lower power, instant-on, smaller footprint
- **Server for heavy lifting** → Easier updates, handles API rate limits
- **UPnP over local audio** → Flexible speaker placement, better audio quality

---

## License

MIT

## Contributing

PRs welcome! Check the Development Plan above for what needs work.
