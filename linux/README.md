# RadioWall — Linux port

See [PLAN.md](PLAN.md) for the full plan.

## Current state

Step 1 of the build order: scaffold + pygame emulator splash screen. Run it to confirm your Python env works and to preview the 256×64 canvas you'll be designing for.

## Run the emulator (Windows / any dev machine)

Requires Python 3.11+.

```bash
cd linux
python -m venv .venv
.venv\Scripts\activate             # PowerShell: .venv\Scripts\Activate.ps1
pip install -e .
set RADIOWALL_EMULATE=1              # PowerShell: $env:RADIOWALL_EMULATE = "1"
python -m radiowall
```

A pygame window pops up showing the 256×64 OLED contents, upscaled 4×.
Close the window or Ctrl+C in the terminal to exit.

## Run on the Pi later

```bash
pip install -e .[pi]
python -m radiowall        # no emulate env var — drives real SSD1322 over SPI
```

## Layout

```
linux/
├── PLAN.md              ← master plan
├── README.md            ← this file
├── pyproject.toml
└── radiowall/
    ├── __init__.py
    ├── main.py          ← entry point (splash for now)
    └── display/
        ├── __init__.py
        └── factory.py   ← pygame emulator vs real SSD1322
```

Everything else (Radio.garden, LinkPlay, input handling, state machine, logging, status API) comes next — see PLAN.md build order.
