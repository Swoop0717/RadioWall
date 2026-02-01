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
│  │                         │ Radio Wien 📻   │               │  │
│  │  5V Power (via pins) →  │ Vienna, Austria │               │  │
│  │                         └─────────────────┘               │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │ WiFi + MQTT
                              ▼
                    ┌─────────────────┐
                    │  Home Server    │  (N100 or Raspberry Pi)
                    │  - Radio.garden │
                    │  - UPnP control │
                    └─────────────────┘
                              │ UPnP/DLNA
                              ▼
                        🔊 WiiM Amp Pro
```

## Hardware

| Component | Model | Status |
|-----------|-------|--------|
| Touch Panel | 9" Capacitive (XY-PG9020-FPC-A17) with USB controller | ✅ Have |
| ESP32 | LILYGO T-Display-S3-Long (3.4" AMOLED, 640×180) | ✅ Have |
| Server | N100 mini PC (or Raspberry Pi 3B+ for dev) | ✅ Have |
| Speaker | WiiM Amp Pro (UPnP/DLNA) | ✅ Have |
| USB-C OTG adapter | USB-A Female → USB-C Male | 📦 Ordered |
| USB-C breakout | For powering ESP32 via 5V pin | 📦 Ordered |
| LiPo Battery | 3000mAh 3.7V, JST 1.25mm connector | 📦 Ordered |

### ESP32 Power Setup
- USB-C port is used for touch panel (USB Host mode)
- Power via 5V + GND pins (from USB breakout or battery)
- Battery connector: JST-GH 1.25mm 2-pin

## Software Components

### 1. Server (Python) - `server/`
Runs on N100 or Raspberry Pi. Handles the heavy lifting.

**Responsibilities:**
- MQTT broker communication (receive touch coords, send now-playing)
- Radio.garden API (fetch places, find nearest stations, get stream URLs)
- Coordinate conversion (pixel X/Y → lat/long)
- UPnP/DLNA control (send stream to WiiM Amp)

**Key files to create:**
- `server/radio_garden.py` - API client
- `server/coordinates.py` - Pixel to lat/long conversion
- `server/upnp_streamer.py` - UPnP device discovery and control
- `server/mqtt_handler.py` - MQTT pub/sub
- `server/main.py` - Orchestration
- `server/config.yaml` - Configuration

### 2. ESP32 Firmware (C++/Arduino) - `esp32/`
Runs on T-Display-S3-Long. Lightweight touch + display.

**Responsibilities:**
- USB Host mode to read touch panel HID events
- Extract X/Y coordinates from touch
- Publish touch events to MQTT
- Subscribe to now-playing updates
- Display station info on AMOLED screen
- Power management (dim display when idle)

**Key files to create:**
- `esp32/src/main.cpp` - Main entry point
- `esp32/src/usb_touch.cpp` - USB Host HID reading
- `esp32/src/mqtt_client.cpp` - MQTT communication
- `esp32/src/display.cpp` - AMOLED display control
- `esp32/src/config.h` - Configuration (WiFi, MQTT, etc.)

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
# List all places with radio stations
GET http://radio.garden/api/ara/content/places
# Returns: {"data": {"list": [{"id": "...", "title": "Vienna", "country": "Austria", "geo": [16.37, 48.21], "size": 42}, ...]}}
# NOTE: geo is [longitude, latitude] not [lat, long]!

# Get stations at a place
GET http://radio.garden/api/ara/content/page/{place_id}/channels

# Get stream URL (redirects to actual stream)
GET http://radio.garden/api/ara/content/listen/{station_id}/channel.mp3
```

## Coordinate Conversion

Map uses equirectangular projection (Plate Carrée). Conversion is linear:

```python
def pixel_to_latlong(x, y, touch_width, touch_height):
    # Assuming full world map bounds
    longitude = (x / touch_width) * 360 - 180   # -180 to +180
    latitude = 90 - (y / touch_height) * 180    # +90 to -90
    return latitude, longitude
```

Calibration needed for real installation (touch area vs map bounds).

## Development Phases

### Phase 0: Hardware Testing ⏳
- [ ] Test touch panel on desktop PC (verify USB HID works)
- [ ] Test touch panel on Raspberry Pi
- [ ] Test ESP32 display basics
- [ ] Test WiiM UPnP discovery

### Phase 1: Server Application
- [ ] Radio.garden API client
- [ ] Coordinate conversion with calibration
- [ ] UPnP/DLNA streaming to WiiM
- [ ] MQTT handler
- [ ] Integration

### Phase 2: ESP32 Firmware
- [ ] USB Host mode for touch panel
- [ ] MQTT client
- [ ] Display UI for "Now Playing"
- [ ] Power management

### Phase 3: Integration
- [ ] End-to-end testing
- [ ] Calibration tool
- [ ] Error handling

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
- Resolution: ~1024×600 (verify with actual device)

### Power Budget
- ESP32 + display + touch: ~110-180mA active, ~35-65mA idle
- 3000mAh battery → ~1-2 days active, ~2-4 days idle

## Commands

### Server
```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m main
```

### ESP32
```bash
cd esp32
pio run -t upload        # Build and upload
pio device monitor       # Serial monitor
```

### MQTT Testing
```bash
# Subscribe to all topics
mosquitto_sub -h localhost -t "radiowall/#" -v

# Simulate touch event
mosquitto_pub -h localhost -t "radiowall/touch" -m '{"x":512,"y":300}'
```

## File Structure

```
RadioWall/
├── CLAUDE.md              # This file
├── README.md              # Project documentation
├── docs/
│   └── hardware_testing.md
├── server/
│   ├── requirements.txt
│   ├── config.example.yaml
│   ├── radio_garden.py
│   ├── coordinates.py
│   ├── upnp_streamer.py
│   ├── mqtt_handler.py
│   └── main.py
├── esp32/
│   ├── platformio.ini
│   └── src/
│       ├── config.example.h
│       ├── main.cpp
│       ├── usb_touch.cpp
│       ├── mqtt_client.cpp
│       └── display.cpp
└── playground.ipynb       # Original prototype (reference only)
```

## Current Status

**Waiting for:** USB-C OTG adapter and USB-C breakout board to arrive (shipping).

**Next steps:**
1. Test touch panel on desktop/laptop (can do now)
2. Start server development (can do now)
3. Test ESP32 USB Host mode (when adapters arrive)
