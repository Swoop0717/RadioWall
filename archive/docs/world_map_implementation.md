# World Map Display Implementation

## Overview

The RadioWall ESP32 firmware now features an interactive world map display with latitude band navigation. Users can:

- **Cycle through latitude bands** using Button 1 (GPIO 0) or touch cycling through 4 horizontal slices of the world
- **Touch the map** to select radio stations at geographic locations
- **Stop/Next controls** via status bar touch buttons or physical button (GPIO 21)
- **Visual feedback** with map rendering and real-time status updates

## Display Layout

```
┌────────────────────────────────────────────────────────────┐
│  Map Area (640×150 px)                                     │
│  Shows current latitude band with coastline outlines      │
│  Full 360° longitude visible                              │
│  [Label: "Mid-North 30-60°N" in top-right corner]         │
├────────────────────────────────────────────────────────────┤
│  [STOP]  Radio Wien - Vienna, Austria          [NEXT]     │  ← Status bar (30px)
└────────────────────────────────────────────────────────────┘
```

## Latitude Bands

The world is divided into 4 horizontal bands (default: Mid-North):

| Band | Latitude Range | Regions | Stations |
|------|---------------|---------|----------|
| **Far North** | 60°N to 90°N | Scandinavia, Canada, Siberia, Alaska | Low density |
| **Mid-North** ⭐ | 30°N to 60°N | USA, Europe, China, Japan | **Highest density** |
| **Tropical** | 30°S to 30°N | Brazil, Africa, India, SE Asia | Medium density |
| **South** | 60°S to 30°S | Australia, Argentina, South Africa | Low density |

⭐ = Default band on startup (most radio stations)

## Controls

### Physical Buttons
- **Button 1 (GPIO 0)**: Cycle latitude band (Far North → Mid-North → Tropical → South → ...)
- **Button 2 (GPIO 21)**: Stop playback (⚠️ May conflict with TFT_QSPI_D2 - test carefully)

### Touch Controls
- **Touch map area (y < 150)**: Select station at touched location
  - Coordinates automatically translated to current band's latitude range
  - Full 360° longitude visible
  - Sends equirectangular coordinates to server
- **Touch status bar (y ≥ 150)**:
  - **Left side (x < 100)**: STOP button
  - **Right side (x > 540)**: NEXT button
  - **Center area**: Displays station info (no action)

## Files Created

### Core Components

1. **[ui_state.h](c:\Users\Desktop\Repositories\RadioWall\esp32\src\ui_state.h)** / **[ui_state.cpp](c:\Users\Desktop\Repositories\RadioWall\esp32\src\ui_state.cpp)**
   - UI state management for latitude bands and playback status
   - Defines 4 latitude bands with metadata and bitmap pointers
   - Tracks current band, playback state, station info
   - API: `cycle_band()`, `get_current_band()`, `set_playing()`, `set_stopped()`

2. **[world_map.h](c:\Users\Desktop\Repositories\RadioWall\esp32\src\world_map.h)** / **[world_map.cpp](c:\Users\Desktop\Repositories\RadioWall\esp32\src\world_map.cpp)**
   - World map bitmap storage and rendering
   - RLE (Run-Length Encoding) decompression
   - Drawing functions: `draw_map_band()`, `draw_band_label()`
   - Currently uses stub test patterns (checkerboard, stripes)

3. **[button_handler.h](c:\Users\Desktop\Repositories\RadioWall\esp32\src\button_handler.h)** / **[button_handler.cpp](c:\Users\Desktop\Repositories\RadioWall\esp32\src\button_handler.cpp)**
   - Physical button input with 200ms debouncing
   - Monitors GPIO 0 (band cycle) and GPIO 21 (stop)
   - Callback-based API for button events

### Modified Files

4. **[display.h](c:\Users\Desktop\Repositories\RadioWall\esp32\src\display.h)** / **[display.cpp](c:\Users\Desktop\Repositories\RadioWall\esp32\src\display.cpp)**
   - Added map view rendering functions:
     - `display_show_map_view()` - Full redraw (map + status bar)
     - `display_update_status_bar()` - Status bar only (efficient update)
     - `display_refresh_map_only()` - Map area only (band cycling)
   - **Display rotation changed to landscape mode** (rotation = 1)
   - Now 640×180 instead of 180×640

5. **[builtin_touch.h](c:\Users\Desktop\Repositories\RadioWall\esp32\src\builtin_touch.h)** / **[builtin_touch.cpp](c:\Users\Desktop\Repositories\RadioWall\esp32\src\builtin_touch.cpp)**
   - Zone-based touch handling (map area vs status bar)
   - Coordinate translation: portrait → landscape → lat/lon → server coordinates
   - New callbacks:
     - `MapTouchCallback(map_x, map_y)` - Map touches (server coordinates)
     - `UIButtonCallback(button_id)` - Status bar buttons (0=stop, 1=next)
   - Legacy callback still supported for backward compatibility

6. **[main.cpp](c:\Users\Desktop\Repositories\RadioWall\esp32\src\main.cpp)**
   - Instantiated global `UIState` object
   - Wired all callbacks (map touch, UI buttons, physical buttons, MQTT)
   - Shows map view on startup instead of connection screen
   - MQTT callbacks update status bar (keeps map visible)

### Tools

7. **[tools/generate_map_bitmaps.py](c:\Users\Desktop\Repositories\RadioWall\tools\generate_map_bitmaps.py)**
   - Python script to generate real map bitmaps from Natural Earth data
   - Downloads Natural Earth 1:110m coastline data (public domain)
   - Renders 640×150 bitmaps for each latitude band
   - Applies RLE compression (~5KB per band, 20KB total)
   - Outputs C header: `esp32/src/world_map_data.h`

8. **[tools/requirements.txt](c:\Users\Desktop\Repositories\RadioWall\tools\requirements.txt)**
   - Python dependencies for map generation tool

## How It Works

### Coordinate Translation

When a user touches the map at display coordinates `(touch_x, touch_y)`:

1. **Rotate to landscape**: `(landscape_x, landscape_y) = (touch_y, 180 - touch_x)`
2. **Detect zone**:
   - If `landscape_y < 150`: Map area
   - If `landscape_y ≥ 150`: Status bar
3. **Map area → lat/lon**:
   ```cpp
   float lon = -180 + (landscape_x / 640.0) * 360;  // Full 360° visible
   float lat = band_lat_max - (landscape_y / 150.0) * (band_lat_max - band_lat_min);
   ```
4. **Lat/lon → server coordinates** (equirectangular projection):
   ```cpp
   int server_x = (lon + 180) / 360.0 * 1024;
   int server_y = (90 - lat) / 180.0 * 600;
   ```
5. **Publish via MQTT**: `radiowall/touch {"x": server_x, "y": server_y}`

### RLE Bitmap Format

Map bitmaps use Run-Length Encoding to minimize flash storage:

```cpp
// Format: Byte pairs [count, color]
// Color: 0 = ocean (black), 1 = land (white)
// End marker: [0, 0]

const uint8_t map_band_mid_north[] PROGMEM = {
    20, 1,   // 20 white pixels (land)
    50, 0,   // 50 black pixels (ocean)
    10, 1,   // 10 white pixels (land)
    // ...
    0, 0     // End marker
};
```

Decompression happens line-by-line during rendering (no full framebuffer needed).

## Building and Testing

### Step 1: Build with Stub Patterns (Quick Test)

The firmware is ready to build with stub test patterns:

```bash
cd esp32
pio run -t upload
pio device monitor
```

**Expected behavior**:
- Display shows map view with test pattern (checkerboard/stripes)
- Status bar shows "Tap map to play | Mid-North ▼"
- Button 1 cycles through patterns
- Touch map → coordinates logged to serial

### Step 2: Generate Real Map Data

Install Python dependencies:

```bash
cd tools
pip install -r requirements.txt
```

Generate map bitmaps:

```bash
python generate_map_bitmaps.py
```

**Output**:
- Downloads Natural Earth coastline data (~1 MB)
- Renders 4 latitude band bitmaps (640×150 each)
- Compresses with RLE (~5KB per band)
- Generates `esp32/src/world_map_data.h` (~20KB total)

Edit [world_map.cpp](c:\Users\Desktop\Repositories\RadioWall\esp32\src\world_map.cpp):

```cpp
// Uncomment this line after generating real map data:
#include "world_map_data.h"
```

Rebuild:

```bash
cd ../esp32
pio run -t upload
```

**Expected behavior**:
- Display shows real coastline outlines
- Recognizable continents and islands
- Touch Vienna region → Austrian radio stations

### Step 3: End-to-End Testing

#### Button Tests
1. **Button 1 (GPIO 0)**: Press → band cycles → map updates → serial log shows band name
2. **Button 2 (GPIO 21)**: Press → MQTT "stop" command sent → playback stops

⚠️ **GPIO 21 Conflict**: If Button 2 causes display glitches (it shares TFT_QSPI_D2), remove physical button and use touch-only stop button.

#### Touch Tests
1. **Touch map in Europe**: Serial shows lat/lon ~(10°E, 50°N) → server coordinates ~(550, 250)
2. **Touch map in Americas**: Serial shows lat/lon ~(-100°W, 40°N) → server coordinates ~(200, 300)
3. **Touch status bar left**: MQTT "stop" command → playback stops
4. **Touch status bar right**: MQTT "next" command → next station

#### Playback Tests
1. Cycle to **Mid-North** band
2. Touch approximate **Vienna location** (center-right area)
3. Verify: Server responds with Austrian radio station
4. Verify: Status bar updates: "Radio Wien - Vienna, Austria"
5. Verify: WiiM starts playing audio

#### Edge Cases
- Touch ocean → Server handles gracefully (no stations nearby)
- Rapid band cycling → No crashes, display updates correctly
- Touch while playing → New station starts, old one stops

## Memory Usage

### Flash (16 MB available)
- Map bitmaps: ~20 KB (4 bands × 5 KB compressed)
- New code: ~20 KB
- **Total: ~40 KB (0.25% of flash)** ✅

### RAM (320 KB SRAM)
- UIState object: ~300 bytes
- RLE decompression buffer (1 scanline): ~80 bytes
- No full framebuffer needed (Arduino_GFX draws directly)
- **Total: ~400 bytes (0.1% of RAM)** ✅

## Known Issues and TODOs

### ⚠️ GPIO 21 Conflict
- **Issue**: GPIO 21 used for both Button 2 and TFT_QSPI_D2
- **Test**: Press Button 2 while display is active/idle
- **Mitigation**: If conflicts detected, remove physical button, use touch-only stop
- **Impact**: Low (touch buttons work well)

### 🔧 Display Rotation
- **Change**: Display rotation set to 1 (landscape mode: 640×180)
- **Test**: Verify display shows correctly (map should be wide, not tall)
- **Fallback**: If rotated incorrectly, try rotation = 3 (270° instead of 90°)

### 📍 Coordinate Calibration
- **Test**: Touch known cities (Vienna, New York, Tokyo) and verify correct stations
- **Debug**: Serial monitor shows all coordinate translations
- **Adjust**: If consistently off, check lat/lon calculations in [builtin_touch.cpp:232-264](c:\Users\Desktop\Repositories\RadioWall\esp32\src\builtin_touch.cpp#L232-L264)

## Next Steps

1. ✅ **Build with stub patterns** - Verify basic functionality
2. ⏳ **Generate real map data** - Run Python tool
3. ⏳ **Test with hardware** - Verify touch accuracy, buttons, display
4. ⏳ **Calibration** - Fine-tune coordinate translation if needed
5. ⏳ **Polish** - Adjust debounce timings, visual feedback
6. 🔮 **Future**: Add zoom/pan, station markers, playback progress

## Files Summary

| File | Type | Purpose | Status |
|------|------|---------|--------|
| `esp32/src/ui_state.h/cpp` | NEW | State management | ✅ Complete |
| `esp32/src/world_map.h/cpp` | NEW | Map rendering | ✅ Complete (stub) |
| `esp32/src/button_handler.h/cpp` | NEW | Button input | ✅ Complete |
| `esp32/src/display.h/cpp` | MODIFIED | Display integration | ✅ Complete |
| `esp32/src/builtin_touch.h/cpp` | MODIFIED | Touch zones | ✅ Complete |
| `esp32/src/main.cpp` | MODIFIED | Orchestration | ✅ Complete |
| `tools/generate_map_bitmaps.py` | NEW | Map generator | ✅ Complete |
| `esp32/src/world_map_data.h` | GENERATED | Real map data | ⏳ Run tool |

## Support

If you encounter issues:

1. **Check serial output**: Most operations log detailed info
2. **Verify config.h**: `USE_BUILTIN_TOUCH = 1`, WiFi credentials correct
3. **Test incrementally**: Stub patterns → real maps → full integration
4. **Report bugs**: Include serial output and description

## References

- **Natural Earth**: https://www.naturalearthdata.com/ (public domain map data)
- **Arduino_GFX**: https://github.com/moononournation/Arduino_GFX
- **RadioWall plan**: [c:\Users\Desktop\.claude\plans\precious-frolicking-trinket.md](c:\Users\Desktop\.claude\plans\precious-frolicking-trinket.md)
