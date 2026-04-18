# RadioWall — Linux port

See [PLAN.md](PLAN.md) for the full plan and Build Order.

## Current state

Scaffold + pygame emulator mockup of the "now playing" screen. Real display driver (ST7789 1.14") in progress.

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

A pygame window pops up showing the display, upscaled. Close the window or Ctrl+C to exit.

## Pi setup — start to finish

Verified on: **Raspberry Pi 3 B+ (1 GB), DietPi (Debian Trixie, Python 3.13), microSD**.

### 1. Hardware prerequisites

- **5.1 V / 2.5 A PSU with a thick USB cable.** A weak PSU silently throttles the SoC to a crawl — if your build feels slow, run `vcgencmd get_throttled` (expect `0x0`; anything non-zero = under-voltage).
- Good WiFi signal (5 GHz preferred on the Pi 3 B+). Under-voltage also kills WiFi throughput.
- The display HAT plugged in **only after** initial setup — easier to SSH without it.

### 2. Flash DietPi + first boot

1. Flash DietPi image to the microSD.
2. Edit `dietpi-wifi.txt` and `dietpi.txt` on the boot partition: fill in WiFi SSID/password and set a hostname (e.g. `radiowall`).
3. Boot — self-install takes ~5 min.
4. Find the Pi on your LAN: `ping radiowall.local` or check your router's DHCP list.
5. `ssh root@<ip>` — default password is whatever you set during flash.

### 3. Increase swap (do this before any pip install)

Pi 3 B+ has 1 GB RAM. Compiling wheels or running VS Code's remote server will OOM without more swap.

```bash
/boot/dietpi/func/dietpi-set_swapfile 2048
```

### 4. Install system packages

Use apt for heavy wheels that would otherwise compile from source for 10+ minutes:

```bash
apt update
apt install -y git python3-pip python3-venv \
    python3-pygame python3-pil python3-yaml python3-requests python3-evdev
```

### 5. Clone + install RadioWall

```bash
git clone https://github.com/Swoop0717/RadioWall.git
cd RadioWall && git checkout linux-port && cd linux

# venv with --system-site-packages so pip sees the apt-installed wheels
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e .[pi]
```

`pip` should report `Requirement already satisfied` for pygame/pillow/requests/pyyaml/evdev and only fetch the small pure-Python packages (luma.oled, luma.emulator, gpiod) from piwheels.

### 6. Enable SPI (needed for the display HAT)

```bash
dietpi-config
# Advanced Options → SPI state → On → back out → reboot
```

Confirm after reboot:

```bash
ls /dev/spidev0.*
# expect: /dev/spidev0.0  /dev/spidev0.1
```

### 7. Plug in the display HAT

With the Pi **powered off**:

- Board: a 1.14" 240×135 ST7789 "Pi TFT" (Adafruit Mini PiTFT or a Chinese clone with the same 26-pin footprint and 2 buttons)
- Align the 26-pin female socket with the Pi's 40-pin header at the **microSD corner** (pin 1)
- Display facing up, buttons on the outer edge, remaining 14 pins of the Pi header exposed past the far edge
- Press straight down until fully seated

Power on, SSH back in, and you're ready to run the app.

### 8. Run it

```bash
# drives the real display
python -m radiowall

# force emulator even on the Pi (useful for headless testing)
RADIOWALL_EMULATE=1 python -m radiowall
```

## Pitfalls we hit (and how to spot them)

| Symptom | Likely cause | Fix |
|---|---|---|
| Everything "feels slow" — apt, pip, SSH | **Under-volt throttling** (`vcgencmd get_throttled` non-zero) | Proper 5.1 V/2.5 A PSU + thick cable |
| VS Code Remote-SSH crashes the window | Pi is OOM — VS Code server + pip = too much on 1 GB | Don't use Remote-SSH on Pi 3 B+; edit on dev machine, `git push`/`pull` to deploy |
| `pip install` compiles for 10+ min | No prebuilt arm64 wheel for your Python version | Install the `python3-X` apt package; use `venv --system-site-packages` |
| `pip install` fails on `evdev` with "linux/input.h missing" | `evdev` needs kernel headers to compile | `apt install python3-evdev` (not `linux-headers`) |
| `/dev/spidev0.*` missing after enabling SPI | Module not loaded yet | `reboot`, then check `lsmod | grep spi` |
| Pi unreachable after plugging in HAT | Misaligned header (shorted rails) or under-volt when display draws current | Power off, reseat HAT on correct pins (1–26), re-check PSU |

## Porting to another SBC

**Raspberry Pi family (4, 5, Zero 2 W)**: identical steps. Pi 5 is dramatically faster; Zero 2 W's 512 MB RAM will struggle even with swap — lean harder on apt, avoid pip from source.

**Orange Pi / Rock / other non-Broadcom SBCs**: DietPi supports them and the pip steps are unchanged, but:
- **GPIO pinouts differ** — the Pi TFT HAT won't plug in as-is; you'd hand-wire SPI + buttons
- SPI device may appear as `/dev/spidev1.0` instead of `/dev/spidev0.0` — our factory needs a parameter
- Kernel header packages are named differently

The Python code is portable; hardware config (SPI bus/device, GPIO pins for buttons/backlight) needs a config-file or env-var knob.

## Layout

```
linux/
├── PLAN.md              ← master plan, build order, design decisions
├── README.md            ← this file
├── pyproject.toml
└── radiowall/
    ├── __init__.py
    ├── main.py          ← entry point, VFD-style mockup
    └── display/
        ├── __init__.py
        ├── factory.py   ← picks emulator / SSD1322 / ST7789 driver
        └── fonts.py     ← platform-aware font loading
```

Everything else (Radio.garden, LinkPlay, input handling, state machine, logging, status API) comes next — see PLAN.md build order.
