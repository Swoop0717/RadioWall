# RadioWall 🗺️📻

An interactive world map that plays local radio stations when you touch a location. Touch Vienna, hear Austrian radio. Touch Tokyo, hear Japanese radio. No screen, no glowing display — just a beautiful physical map behind invisible touch-sensing glass.

## The Vision

A framed physical world map (paper or cloth) with a transparent capacitive touch layer. Touch anywhere on the map, and a Raspberry Pi finds the nearest radio stations and streams them to your speakers via your home network.

```
┌─────────────────────────────────────────────────────────┐
│                     Picture Frame                        │
│  ┌───────────────────────────────────────────────────┐  │
│  │            Glass + PCAP Touch Foil                │  │
│  │              (touch surface)                      │  │
│  ├───────────────────────────────────────────────────┤  │
│  │                                                   │  │
│  │         Physical Paper/Cloth World Map            │  │
│  │            (equirectangular projection)           │  │
│  │                                                   │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         │ USB (touch input)
                         ▼
              ┌─────────────────────┐
              │    Raspberry Pi     │
              │  - Headless service │
              │  - Touch → lat/long │
              │  - Radio.garden API │
              │  - UPnP streaming   │
              └─────────────────────┘
                         │ Network (UPnP/DLNA)
                         ▼
                   🔊 Network Speaker
                   (e.g. WiiM Amp Pro)
```

## Hardware

### Current Development Setup
- Raspberry Pi (any model with WiFi + USB)
- USB Touchscreen for testing (e.g., 10.1" HDMI + USB touch display)
- Network speaker with UPnP/DLNA support (e.g., WiiM Amp Pro)

### Target Production Setup
- **PCAP Touch Foil**: Transparent capacitive touch film (available 32"–180"+)
  - Mounts behind glass, works through up to 20mm thickness
  - USB HID output, plug-and-play on Linux
  - Suppliers: CJTouch, Keetouch, Pro Display, various AliExpress vendors
- **Physical Map**: Equirectangular projection (Plate Carrée) for linear coordinate conversion
- **Frame**: Custom frame with glass front, map behind, touch foil between
- **Raspberry Pi**: Hidden in frame or mounted behind
- **Network Speaker**: Any UPnP/DLNA compatible speaker/amplifier

### Why PCAP Touch Foil?
- Works with a static image (no display needed!)
- Can be mounted behind glass with your physical map
- USB plug-and-play, appears as standard HID input device
- Available in sizes up to 180" for full wall installations
- ~90% transparency, invisible when installed
- Works through glass up to 8-20mm depending on model

## Software Architecture

```
radiowall/
├── src/
│   ├── touch_input.py      # USB HID touch event reader
│   ├── coordinates.py      # Touch X/Y → Lat/Long conversion
│   ├── radio_garden.py     # Radio.garden API client
│   ├── upnp_streamer.py    # UPnP/DLNA streaming to speakers
│   └── main.py             # Main service orchestration
├── config/
│   └── config.yaml         # Calibration & settings
├── tests/
├── requirements.txt
└── README.md
```

### Core Components

1. **Touch Input** (`touch_input.py`)
   - Reads USB HID events from touch foil/screen
   - Emits touch coordinates (X, Y in pixels)
   - Handles multi-touch (use first touch point)

2. **Coordinate Conversion** (`coordinates.py`)
   - Converts pixel X/Y to latitude/longitude
   - For equirectangular projection: linear transformation
   - Calibration support for different map sizes
   
   ```python
   # Equirectangular projection conversion
   longitude = (x / width) * 360 - 180    # -180 to +180
   latitude = 90 - (y / height) * 180     # +90 to -90
   ```

3. **Radio.garden Client** (`radio_garden.py`)
   - Fetches list of all places with radio stations
   - Finds N nearest stations to given coordinates
   - Gets stream URL for selected station
   
   ```
   API Endpoints:
   - GET /api/ara/content/places           → List of all places
   - GET /api/ara/content/page/{id}/channels → Stations at a place  
   - GET /api/ara/content/listen/{id}/channel.mp3 → Audio stream
   ```

4. **UPnP Streamer** (`upnp_streamer.py`)
   - Discovers UPnP/DLNA renderers on network
   - Sends radio stream URL to speaker
   - Controls playback (play/stop/volume)

5. **Main Service** (`main.py`)
   - Orchestrates all components
   - Runs as headless systemd service
   - Handles configuration and calibration

## Development Phases

### Phase 1: Core Application ✅ → 🚧
- [x] Radio.garden API integration (basic version in playground.ipynb)
- [x] Find nearest stations to coordinates
- [x] Get audio stream URL
- [ ] Refactor into clean Python modules
- [ ] USB HID touch input reader (Linux evdev)
- [ ] Proper coordinate conversion with calibration
- [ ] UPnP/DLNA streaming to network speakers

### Phase 2: Raspberry Pi Deployment
- [ ] Headless service setup
- [ ] systemd service file
- [ ] Auto-start on boot
- [ ] WiFi configuration
- [ ] Calibration tool/script

### Phase 3: Hardware Integration
- [ ] Test with USB touchscreen
- [ ] Test with PCAP touch foil
- [ ] Frame design and construction
- [ ] Final calibration for production map

### Phase 4: Polish & Features
- [ ] Station selection when multiple nearby (audio feedback?)
- [ ] Optional: ESP32 "now playing" display via MQTT
- [ ] Optional: Physical volume knob
- [ ] Optional: LED indicator for current region

## Radio.garden API

Radio.garden doesn't have an official public API, but these endpoints work:

```bash
# Get all places with radio stations
curl http://radio.garden/api/ara/content/places

# Response contains:
# { "data": { "list": [
#   { "id": "...", "title": "Vienna", "country": "Austria", 
#     "geo": [16.37, 48.21], "size": 42 },
#   ...
# ]}}

# Get stations at a place
curl http://radio.garden/api/ara/content/page/{place_id}/channels

# Stream a station (returns audio/mpeg)
curl http://radio.garden/api/ara/content/listen/{station_id}/channel.mp3
```

**Note**: The `geo` field is `[longitude, latitude]` (not lat/long!)

## Coordinate Systems

### Equirectangular Projection (Plate Carrée)
The simplest map projection with linear coordinate conversion:
- X axis = Longitude (-180° to +180°)
- Y axis = Latitude (+90° to -90°, inverted because Y grows downward)

For a map image of size `W × H`:
```python
longitude = (x / W) * 360 - 180
latitude = 90 - (y / H) * 180
```

### Calibration
For physical installations, you may need to calibrate for:
- Touch area offset from map edge
- Touch area size vs actual map size
- Map orientation (if rotated)

Store calibration in `config/config.yaml`:
```yaml
touch:
  device: "/dev/input/event0"  # or auto-detect
  width: 1920
  height: 1080

map:
  # Pixel coordinates of map corners on touch surface
  top_left: [50, 30]
  bottom_right: [1870, 1050]
  
  # Geographic bounds (for non-standard map crops)
  lat_north: 90
  lat_south: -90
  lon_west: -180
  lon_east: 180

audio:
  upnp_device: "WiiM Amp Pro"  # or auto-discover
  n_stations: 20  # stations to consider for selection
  
selection:
  mode: "random"  # or "nearest" or "popular"
```

## Installation

### Development (any Linux machine)
```bash
git clone https://github.com/Swoop0717/RadioWall.git
cd RadioWall
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Raspberry Pi Deployment
```bash
# Install system dependencies
sudo apt update
sudo apt install python3-pip python3-venv python3-evdev

# Clone and setup
git clone https://github.com/Swoop0717/RadioWall.git
cd RadioWall
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install as service
sudo cp radiowall.service /etc/systemd/system/
sudo systemctl enable radiowall
sudo systemctl start radiowall
```

## Hardware Resources

### PCAP Touch Foils
- [Pro Display Touch Foils](https://prodisplay.com/touch-screens/interactive-overlays/pcap-touch-foil/) (UK)
- [Keetouch](https://keetouch.eu/) (EU)
- [CJTouch](https://www.cjtouch.com/) (China/Global)
- AliExpress: Search "capacitive touch foil USB" (budget option)

### Maps (Equirectangular Projection)
- NASA Blue Marble: https://visibleearth.nasa.gov/collection/1484/blue-marble
- Natural Earth: https://www.naturalearthdata.com/
- Custom print services for large format

### Network Speakers with UPnP/DLNA
- WiiM Amp / WiiM Pro
- Sonos (via sonos-http-api)
- Any DLNA-compatible speaker

## Legacy Notes

The original prototype (`playground.ipynb`) used:
- VLC for local audio playback
- matplotlib for displaying a map on screen
- pynput for mouse click detection

This worked but required a display. The new architecture is completely headless and uses network audio instead.

## License

MIT

## Contributing

PRs welcome! See Development Phases above for what needs work.
