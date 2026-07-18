# RadioWall

An interactive world map that plays local radio stations when you touch a
location. Touch Vienna, hear Austrian radio. Touch Tokyo, hear Japanese radio.

## The Vision

A framed **physical world map** (paper or cloth) with an **invisible touch
layer**. No glowing screens on the map itself — just an analog map you can
touch to explore the world's radio stations, a small OLED status display, and
one rotary knob.

```
┌──────────────────────────────────────────────────────────────┐
│                       Picture Frame                           │
│   ┌────────────────────────────────────────────────────┐     │
│   │        Physical World Map (equirectangular)        │     │
│   │               + IR Touch Frame Overlay             │     │
│   └────────────────────────────────────────────────────┘     │
│                            │ USB                              │
│   ┌────────────────────────────────────────────────────┐     │
│   │  Orange Pi Zero 3W ──► 256×64 OLED + rotary knob   │     │
│   └────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
                            │ WiFi / Bluetooth
            ┌───────────────┴───────────────┐
            ▼                               ▼
  ┌─────────────────┐             ┌─────────────────┐
  │  Radio.garden   │             │ WiiM / LinkPlay │
  │  (stations API) │             │ or BT speakers  │
  └─────────────────┘             └─────────────────┘
```

## How It Works

1. Touch the map → convert coordinates to (lat, lon)
2. Find the nearest city in the Radio.garden places database (~12,300 cities,
   auto-refreshed weekly — cities with no live stations are hopped over)
3. Fetch that city's stations live from the Radio.garden API
4. Play: a WiiM speaker streams the URL itself (LinkPlay HTTPS), or the board
   decodes and streams to any Bluetooth speaker (A2DP)

## Features

- **One-knob UI** on a 256×64 OLED: tap = next station (or resume), double-tap
  = cycle 8 audio visualizers, triple-tap = star the current station, hold =
  menu (music keeps playing), hold longer = stop
- **Now playing**: live song titles from ICY stream metadata, revealed in sync
  with what you actually hear
- **History & favorites**: stations that play >30 s are recorded; favorites
  are pinned and replayable from the menu
- **Sleep timer**: oven-style dial (fast-spin acceleration), enforced both
  locally and natively on the WiiM
- **Speakers**: WiiM/LinkPlay discovery via SSDP, multiroom grouping,
  Bluetooth speaker pairing — playback transfers when you switch outputs
- **No phone needed, ever**: WiFi setup, speaker pick, touch calibration and
  everything else happens on-device with the knob
- **Self-maintaining**: weekly places refresh, silent/dead station skipping,
  OLED burn-in protection, visualizers synced to the speaker's real playback
  position

## Hardware

| Component | Used |
|-----------|------|
| Compute | Orange Pi Zero 3W (Allwinner A733, 4 GB) |
| Display | TZT 3.12" 256×64 SSD1322 SPI OLED |
| Dial | EC11 / KY-040 rotary encoder |
| Touch | 55" IR touch frame (USB HID, VID 1FF7) |
| Speaker | WiiM Amp (LinkPlay) and/or any Bluetooth speaker |
| Map | Equirectangular print behind glass (110 × 62 cm touch area) |

See [linux/README.md](linux/README.md) for the full parts list, the Orange Pi
pin-allocation table, board setup, and the collected hardware gotchas (OLED
bus-mode solder jumpers, KY-040 pull-up rail, serial console recovery pins).

## ESP32 Prototypes (legacy)

RadioWall v1 ran standalone on ESP32-S3 hardware (LILYGO T-Display-S3-Long,
later a 55" IR frame over USB Host). That firmware is feature-complete and
preserved — with its docs, map bitmap tooling and early design notes — on the
[`legacy/esp32`](../../tree/legacy/esp32) branch.

## Tools

- [tools/compile_places.py](tools/compile_places.py) — Radio.garden places →
  `places.bin` (the board also refreshes this itself, weekly)
- [tools/generate_tiled_map.py](tools/generate_tiled_map.py) — tileable A3 PDF
  of the world map for tracing onto glass

## License

MIT
