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

### Phase 2: ESP32 Firmware ✅
- [x] Built-in touchscreen working (interrupt-driven, Arduino_GFX)
- [x] Display rendering working (Arduino_AXS15231 driver)
- [x] MQTT client with WiFi reconnect
- [x] Touch coordinate mapping (640×180 → 1024×600)
- [x] End-to-end tested on hardware
- [ ] USB Host mode for external touch panel (waiting for OTG adapter)

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

## Hardware-Specific Learnings (CRITICAL)

### AXS15231B Display Driver - What Works

**IMPORTANT**: The T-Display-S3-Long uses an **AXS15231B** chip which is a **combined display+touch controller**. This has specific requirements:

1. **Use Arduino_GFX library v1.3.7** (bundled in LILYGO examples)
   - ❌ LVGL's driver doesn't work reliably
   - ❌ TFT_eSPI doesn't support AXS15231B
   - ✅ Arduino_GFX has native `Arduino_AXS15231` driver

2. **Use Arduino_DriveBus library v1.1.12** for I2C touch
   - Provides `Arduino_HWIIC` wrapper for interrupt-driven touch
   - Handles proper I2C communication with touch controller

3. **Shared Reset Pin (GPIO 16)** - CRITICAL BUG TO AVOID
   - Display and touch share the **same reset pin** (GPIO 16)
   - ❌ **NEVER reset GPIO 16 after display initialization** - will crash display
   - ✅ Reset once in `display_init()`, then leave it alone
   - In `builtin_touch_init()`, do NOT reset the pin

4. **Power Management Chip (I2C 0x6A)**
   - Must configure before display/touch work properly
   - Write to registers:
     ```cpp
     IIC_WriteC8D8(0x6A, 0x00, 0B00111111);  // Disable ILIM, max current
     IIC_WriteC8D8(0x6A, 0x09, 0B01100100);  // Turn off BATFET
     ```

5. **Backlight Control**
   - Use LEDC PWM (channel 1) for smooth brightness control
   - GPIO 1 (TFT_BL)
   - Smooth fade-in on boot improves user experience

6. **Touch Interrupt (GPIO 11)**
   - Use hardware interrupt, not polling
   - `attachInterrupt(TOUCH_INT, ISR_function, FALLING)`
   - Touch read command: `{0xB5, 0xAB, 0xA5, 0x5A, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00}`
   - Parse: `fingers_number = temp_buf[1]`, `touch_event = temp_buf[2] >> 4`
   - Valid touch: `fingers_number == 1 && touch_event == 0x08`

### ESP32 Firmware Library Setup

**Working Configuration** (esp32/platformio.ini):
```ini
lib_deps =
    knolleary/PubSubClient@^2.8
    bblanchon/ArduinoJson@^6.21.0
    # Arduino_GFX and Arduino_DriveBus in lib/ folder (v1.3.7 and v1.1.12)
```

**Library Folder Structure**:
```
esp32/lib/
├── Arduino_GFX-1.3.7/      # Copied from LILYGO T-Display-S3-Long repo
└── Arduino_DriveBus-1.1.12/ # Copied from LILYGO T-Display-S3-Long repo
```

**Why local libraries?**
- Arduino_GFX from PlatformIO registry had version incompatibilities
- LILYGO bundles specific tested versions that work together
- Copying from their working example ensures compatibility

### Pin Definitions (esp32/src/pins_config.h)

```cpp
// QSPI Display Pins
#define TFT_QSPI_CS   12
#define TFT_QSPI_SCK  17
#define TFT_QSPI_D0   13
#define TFT_QSPI_D1   18
#define TFT_QSPI_D2   21
#define TFT_QSPI_D3   14
#define TFT_QSPI_RST  16  // Shared with touch!
#define TFT_BL        1

// I2C Touch Pins
#define TOUCH_SDA     15
#define TOUCH_SCL     10
#define TOUCH_INT     11  // Hardware interrupt
#define TOUCH_RES     16  // Same as TFT_QSPI_RST
```

### Initialization Order (CRITICAL)

```cpp
void setup() {
    Serial.begin(115200);

    // 1. Display first (includes reset of GPIO 16)
    display_init();

    // 2. WiFi/MQTT
    mqtt_init();

    // 3. Touch last (do NOT reset GPIO 16 again!)
    builtin_touch_init();
}
```

### Errors Encountered and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| Display glitchy/fades to black | Touch reset GPIO 16 after display init | Remove reset from `builtin_touch_init()` |
| LVGL compilation errors | Missing lv_conf.h, wrong paths | Use Arduino_GFX instead of LVGL |
| Arduino_AXS15231 not found | Wrong Arduino_GFX version | Use v1.3.7 from LILYGO lib/ folder |
| Touch not working | Polling instead of interrupt | Use GPIO 11 interrupt with proper ISR |
| No Serial output | `ARDUINO_USB_CDC_ON_BOOT=0` | Set to `=1` in platformio.ini |

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
│   ├── lib/                # Local libraries (from LILYGO examples)
│   │   ├── Arduino_GFX-1.3.7/
│   │   └── Arduino_DriveBus-1.1.12/
│   └── src/
│       ├── config.example.h
│       ├── config.h        # Runtime config (git-ignored)
│       ├── main.cpp
│       ├── builtin_touch.cpp / .h  # Built-in touchscreen (interrupt-driven)
│       ├── usb_touch.cpp / .h      # USB touch panel (skeleton)
│       ├── mqtt_client.cpp / .h
│       ├── display.cpp / .h        # Arduino_GFX display driver
│       └── pins_config.h           # Hardware pin definitions
└── playground.ipynb       # Original prototype (reference only)
```

## Current Status (Updated 2026-02-01)

**Server**: ✅ Running in Docker on N100, end-to-end tested (touch sim → Radio.garden → WiiM playback).

**ESP32 Firmware**: ✅ **FULLY WORKING!** Hardware tested
- ✅ Arduino_GFX display driver (AXS15231B QSPI) rendering properly
- ✅ Built-in touchscreen working (interrupt-driven, I2C)
- ✅ WiFi connected (192.168.0.144 on "Martin_Router_King")
- ✅ MQTT connected (192.168.0.69:1883)
- ✅ Touch coordinate mapping (640×180 → 1024×600) verified
- ✅ End-to-end flow confirmed: Physical touch → MQTT → Server → (radio playback)
- ✅ Visual touch feedback (red circles on display)

**Waiting for**: USB-C OTG adapter and USB-C breakout board (for external 9" touch panel).

**Next steps**:
1. Test with server to verify radio station playback on WiiM
2. Implement USB touch panel support when OTG adapter arrives
3. Add world map display with station indicators

## Hardware-Specific Issues & Solutions (Critical!)

### T-Display-S3-Long Specifics

**CRITICAL: This board uses custom hardware that requires specific handling!**

#### Display Controller: AXS15231B (NOT standard)
- **NOT** compatible with TFT_eSPI library (will cause PSRAM crash)
- **NOT** compatible with standard Arduino_GFX drivers (Arduino_AXS15231B class doesn't exist in v1.3.7)
- Uses **QSPI interface** (not standard SPI)
- Resolution: 640×180 pixels (ultra-wide AMOLED)
- Rotation: Landscape mode is rotation 1

**Display Solutions:**
1. **Option A**: Use LILYGO's custom AXS15231B driver from `examples/TFT/AXS15231B.cpp/h` (complex, includes LVGL integration)
2. **Option B**: Write minimal SPI driver using ESP32 SPI library directly
3. **Option C**: For initial testing, skip display and focus on touch + MQTT first

**Display Pins (QSPI):**
```
CS:  GPIO 12
SCK: GPIO 17
D0:  GPIO 13 (MOSI)
D1:  GPIO 18 (MISO)
D2:  GPIO 21
D3:  GPIO 14
RST: GPIO 16
PWR: GPIO 15 (display power, set HIGH)
```

#### Touch Controller: AXS15231B (integrated with display!)
- **NOT** CST816S (common misconception)
- Touch is integrated into the AXS15231B display IC
- Uses **I2C communication** at address **0x3B**
- Requires custom I2C command sequence (see official example)

**Touch Pins:**
```
SDA: GPIO 15
SCL: GPIO 10
RST: GPIO 16 (shared with display)
```

**Touch Reading Sequence** (from official LILYGO example):
```cpp
// 1. Send read command
uint8_t cmd[] = {0xb5, 0xab, 0xa5, 0x5a, 0x0, 0x0, 0x0, 0x8};
Wire.beginTransmission(0x3B);
Wire.write(cmd, sizeof(cmd));
Wire.endTransmission();

// 2. Request 14 bytes of data
Wire.requestFrom(0x3B, 14);
Wire.readBytes(buffer, 14);

// 3. Extract touch coordinates
uint8_t num_points = buffer[1];
uint8_t gesture = buffer[0];
uint16_t x = ((buffer[2] & 0x0F) << 8) + buffer[3];
uint16_t y = ((buffer[4] & 0x0F) << 8) + buffer[5];
```

**⚠️ CRITICAL FINDING: Touch Requires Display Initialization!**

The AXS15231B touch controller **will NOT report touches** unless the display is initialized first. Testing confirmed:
- I2C communication works (returns 14 bytes)
- Buffer always shows `00 00 00 00...` (0 touch points)
- Touch only works when display driver is running

**Workaround for testing without display:**
Use serial simulation - send `T:x,y` over Serial to trigger touch events.
Example: `T:340,60` simulates touch at display coordinates (340, 60).

**End-to-end testing confirmed working (2026-02-01):**
- ✅ Serial input `T:340,60` received
- ✅ Mapped to (544, 252) on 1024×600 map
- ✅ MQTT published successfully
- ✅ Server responded with "Muhasa Radio 92.3FM, Kano, Nigeria"
- ✅ ESP32 displayed "Now Playing" info via Serial
- ✅ Status updated to "Playing"

### Build Issues Encountered

#### 1. PSRAM Configuration Error
**Error**: `PSRAM ID read error: 0x00ffffff`
**Cause**: platformio.ini had wrong PSRAM settings (`board_build.psram_type = opi`, `-DBOARD_HAS_PSRAM`)
**Solution**: Remove ALL PSRAM configuration - T-Display-S3-Long doesn't use external PSRAM

#### 2. TFT_eSPI Crash
**Error**: `Guru Meditation Error: Core 1 panic'ed (StoreProhibited)` in `TFT_eSPI::init()`
**Cause**: TFT_eSPI doesn't support AXS15231B driver
**Solution**: Don't use TFT_eSPI - use custom driver or Arduino_GFX

#### 3. Arduino_GFX Version Incompatibility
**Error**: `fatal error: esp32-hal-periman.h: No such file or directory`
**Cause**: Arduino_GFX v1.6.4 requires newer ESP32 framework
**Solution**: Use exactly version 1.3.7: `moononournation/GFX Library for Arduino@1.3.7`

#### 4. Missing AXS15231B Driver in Arduino_GFX
**Error**: `error: expected type-specifier before 'Arduino_AXS15231B'`
**Cause**: Arduino_AXS15231B class doesn't exist in Arduino_GFX 1.3.7
**Solution**: LILYGO uses custom driver files, not built-in Arduino_GFX drivers

### Library Compatibility Matrix

| Library | Version | Compatible? | Notes |
|---------|---------|-------------|-------|
| TFT_eSPI | Any | ❌ NO | Crashes - doesn't support AXS15231B |
| Arduino_GFX | 1.6.4+ | ❌ NO | Requires newer ESP32 framework |
| Arduino_GFX | 1.3.7 | ⚠️ PARTIAL | Works but needs custom AXS15231B driver |
| Custom AXS15231B driver | LILYGO | ✅ YES | From `examples/TFT/` in official repo |

### Recommended Development Approach

**Phase 1: Get Touch Working First (Simplest)**
1. Skip display initialization entirely
2. Focus on I2C touch reading
3. Test MQTT connectivity
4. Verify touch → MQTT → server flow works
5. Monitor via Serial output only

**Phase 2: Add Display Later**
1. Copy LILYGO's custom AXS15231B driver files
2. Integrate with existing touch code
3. Add "Now Playing" UI

### Critical Files from LILYGO Repository

For future reference, if you need the display driver:
- Source: https://github.com/Xinyuan-LilyGO/T-Display-S3-Long
- Driver location: `examples/TFT/AXS15231B.cpp` and `.h`
- Touch example: `examples/touch/` (shows I2C commands)
- Pins config: `examples/touch/pins_config.h`

**Note**: The LILYGO examples use their own display driver with LVGL integration. For RadioWall, we only need basic text rendering, so a minimal driver is sufficient.
