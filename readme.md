# RadioWall

An interactive world map that plays local radio stations when you touch a location. Touch Vienna, hear Austrian radio. Touch Tokyo, hear Japanese radio.

## The Vision

A framed **physical world map** (paper or cloth) with an **invisible capacitive touch layer**. No glowing screens on the map itself — just an analog map you can touch to explore the world's radio stations.

```
┌──────────────────────────────────────────────────────────────┐
│                       Picture Frame                           │
│   ┌────────────────────────────────────────────────────┐     │
│   │        Physical World Map (equirectangular)        │     │
│   │               + Touch Panel Overlay                │     │
│   └────────────────────────────────────────────────────┘     │
│                            │ USB                              │
│   ┌────────────────────────────────────────────────────┐     │
│   │    Touch Controller ──► Compute Board ──► WiFi     │     │
│   └────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
  ┌─────────────────┐             ┌─────────────────┐
  │  Radio.garden   │             │  WiiM Speaker   │
  │  (stations API) │             │  (LinkPlay API) │
  └─────────────────┘             └─────────────────┘
```

## Current State

The project has two tracks:

**[esp32/](esp32/)** — Finished ESP32 firmware. Two working prototypes:
- **P1**: LILYGO T-Display-S3-Long, built-in AMOLED + touch. Fully working standalone.
- **P2**: ESP32-S3 + 55" IR touch frame via USB Host. Working, logs over WiFi UDP.

**[linux/](linux/)** *(active)* — Python port on an **Orange Pi Zero 3W (Allwinner A733)**. All final hardware is validated together (2026-07-12): SSD1322 256×64 OLED, EC11/KY-040 rotary encoder, and the 55" IR frame as a plain USB HID device — no USB-host gymnastics. UI mockup + audio visualizers running; the radio logic (Radio.garden/LinkPlay/places lookup) is the remaining port. Why Linux: nicer UI, faster Python iteration, no LittleFS/PSRAM constraints.

Both tracks talk to the same Radio.garden API and the same WiiM speaker over LinkPlay HTTPS.

## How It Works

1. Touch the map → convert pixel coords to (lat, lon)
2. Find the nearest city in the Radio.garden places database (~12,500 cities)
3. Fetch that city's stations from the Radio.garden API
4. Send the station's stream URL to a WiiM speaker via the LinkPlay HTTPS API
5. WiiM streams the audio directly from the internet

No server. No audio processing on the device. The compute board just coordinates.

## Hardware

| Component | Used |
|-----------|------|
| Speaker | WiiM Amp Pro (LinkPlay) |
| Touch | 55" IR touch frame (USB HID, VID 1FF7) |
| Map | Equirectangular print behind glass (110 × 62 cm touch area) |
| Compute (P1/P2) | LILYGO T-Display-S3-Long (ESP32-S3) |
| Compute (Linux track) | Orange Pi Zero 3W (Allwinner A733, 4 GB) |
| Display (Linux track) | TZT 3.12" 256×64 SSD1322 SPI OLED |
| Dial (Linux track) | EC11 / KY-040 rotary encoder |

## ESP32 Firmware

See [esp32/](esp32/) and [CLAUDE.md](CLAUDE.md) for details.

```bash
cd esp32
cp src/config.example.h src/config.h   # edit WiiM IP
pio run -e t-display-s3-long -t upload
pio run -e t-display-s3-long -t uploadfs   # places.bin → LittleFS
```

Environments:
- `t-display-s3-long` — Prototype 1 (built-in display + touch)
- `usb-touch` — Prototype 2 (external IR touch frame)

## Linux Port

See [linux/README.md](linux/README.md) — includes the full parts list, the
Orange Pi pin-allocation table, board setup, and the collected hardware
gotchas (OLED bus-mode solder jumpers, KY-040 pull-up rail, serial console
recovery pins).

## Tools

- [tools/compile_places.py](tools/compile_places.py) — downloads Radio.garden places to `places.bin`
- [tools/generate_map_bitmaps.py](tools/generate_map_bitmaps.py) — renders coastline bitmaps for the ESP32 display
- [tools/generate_tiled_map.py](tools/generate_tiled_map.py) — generates a tileable A3 PDF of the map for tracing onto glass

## License

MIT
