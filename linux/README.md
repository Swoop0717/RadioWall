# RadioWall — Linux port

See [PLAN.md](PLAN.md) for the full plan and Build Order.

## Current state

Running on the **final target hardware** since 2026-07-12: an **Orange Pi
Zero 3W (Allwinner A733)** drives the 3.12" 256×64 **SSD1322** OLED
(`RADIOWALL_DISPLAY=ssd1322`) with the VFD-style "now playing" mockup plus
eight audio-reactive visualizers. An HTTP proxy re-serves the chosen stream to
the WiiM at `:8000/stream.mp3` while a local ffmpeg→FFT path feeds the
visualizer. Board is at `192.168.0.5`, user `orangepi`, key SSH.

The previous dev rig — **Raspberry Pi 3 B+ / DietPi (Trixie)** with the 1.14"
240×135 **ST7789** HAT, systemd service, `/etc/radiowall.env` — still works
unchanged (board profiles auto-detect; see below) and remains the fallback.

Mode cycling was HAT-button-only, so on the Orange Pi the visualizers are
unreachable until the EC11 encoder is wired into `main.py` (next step).

Not yet ported from the ESP32 firmware: the actual radio logic (LinkPlay
client, Radio.garden client, `places.bin` nearest-city lookup, touch→city→play
state machine). The screen content is still a hardcoded mockup. See PLAN.md.

> **Platform note:** PLAN.md originally targeted an **Orange Pi Zero 3W**
> (Allwinner **A733** — not H618 as earlier notes said; see the user manual PDF
> in this dir). **Resolved 2026-07-12: the board was never broken.** It boots
> the official Orange Pi Ubuntu Jammy image (kernel 6.6.x-sun60iw2) fine — it
> just had no WiFi configured and no display attached, so it looked dead.
> Diagnosed via serial console: debug UART is on 40-pin header **pin 8 = board
> TX, pin 10 = board RX, pin 6 = GND** (same positions as a Raspberry Pi),
> 115200 8N1, 3.3 V. Cross-connect TX↔RX; if silent, swap the two data wires
> (adapter silkscreens lie). Power: the PWRIN Type-C does **no PD negotiation**
> — use a plain 5 V/3 A supply via USB-A→C cable, not a PD charger with C-to-C.
> Development now happens on the Orange Pi; the Pi 3 B+ rig remains a working
> fallback (the code is board-agnostic, profiles auto-detect). Note
> DietPi/Armbian do **not** support the A733 — use the official Orange Pi
> images.

## Parts list

### Final build (all validated together 2026-07-12)

| Role | Part | Notes |
|---|---|---|
| Compute | **Orange Pi Zero 3W** (Allwinner A733, 4 GB) + microSD | at `192.168.0.5`; official Ubuntu Jammy image only |
| PSU | plain **5 V / ≥3 A** USB-A brick + **USB-A→USB-C** cable | PWRIN port; **no PD** — C-to-C from a PD charger may deliver nothing |
| Display | TZT 3.12" 256×64 **SSD1322** SPI OLED (16-pin, Ver 2.1) | solder jumpers must be in **4SPI** position (R5+R8); ships in parallel mode |
| Rotation/press input | **KY-040** encoder module (dev) / bare **EC11** (final panel) | KY-040's `+` **must** go to 3.3 V; bare EC11 needs no supply |
| Touch input | 55" **IR touch frame**, USB (CVTouch, VID 1FF7 PID 0013) | plain HID; needs **USB-C OTG adapter** into the middle Type-C (DP) port |
| Speaker | WiiM Amp Pro (`192.168.0.33`) | streams audio itself; the board only coordinates |
| Enclosure | Car-radio shell (planned) | |

### Dev / support gear

| Item | Why it earned its place |
|---|---|
| **CP2102 USB-UART adapter** + 3 DuPont wires | serial console = the only way into a headless board that won't network; solved the "dead" Orange Pi in one session |
| Raspberry Pi 3 B+ (1 GB) + 5.1 V/2.5 A PSU | fallback dev rig, still runs the same code (profile auto-detects) |
| 1.14" 240×135 ST7789 "Pi TFT" HAT (2 buttons) | dev display; proved the OPi SPI/GPIO stack before the OLED went on |
| Pinecil + flux + solder | SMD jumper surgery on the OLED (R6→R5); will solder leads onto bare EC11s |
| Female-female DuPont wires, assorted | everything above; keep spares — crimps fail invisibly |

## Orange Pi Zero 3W pin allocation

Every wire on the 40-pin header in one place. "Free" pins are unlisted.

| Physical pin | Signal | Goes to |
|---|---|---|
| 1 | 3.3 V | KY-040 **+** (pull-up rail — not optional) |
| 6 / 8 / 10 | GND / board TX / board RX | *recovery serial console* (115200 8N1, 3.3 V) — keep free |
| 15 | PE9 | OLED **RES#** (pin 15) · [ST7789 HAT backlight when that display is used] |
| 17 | 3.3 V | OLED **VCC** (pin 2) — **never 5 V** |
| 19 | SPI3 MOSI | OLED **D1/DIN** (pin 5) |
| 20 | GND | OLED **GND** (pin 1) |
| 22 | PD0 | OLED **D/C#** (pin 14) |
| 23 | SPI3 SCLK | OLED **D0/CLK** (pin 4) |
| 24 | SPI3 CS0 | OLED **CS#** (pin 16) |
| 36 | PD2 | encoder **SW** |
| 38 | PB8 | encoder **DT** — ⚠ same pin as I2C1 SDA; don't enable the `i2c1` overlay |
| 39 | GND | encoder **GND** |
| 40 | PB7 | encoder **CLK** — ⚠ same pin as I2C1 SCL |

USB: IR touch frame → **middle Type-C** (the DP/data port) via OTG adapter.
OLED pins 3 and 6–13 (NC + parallel bus) stay unconnected — fine on our unit.

## Inputs (GPIO wiring)

**Rotary encoder (EC11 / KY-040)** — driver in `radiowall/input/encoder.py`.
Same physical pins on the Pi 3 B+ and the Orange Pi Zero 3W (per-board GPIO
numbers resolved by `radiowall/hw/board.py`):

| KY-040 | → **physical pin** | Pi BCM | OPi line |
|---|---|---|---|
| CLK | 40 | GPIO21 | 39 (PB7) |
| DT | 38 | GPIO20 | 40 (PB8) |
| SW | 36 | GPIO16 | 98 (PD2) |
| GND | 39 | — | — |
| + | **3.3 V (pin 1 or 17)** | — | — |

> **`+` is NOT optional on a KY-040** (learned the hard way, 2026-07-12): the
> module has 10 k pull-ups (R1–R3) from CLK/DT/SW to the `+` rail. Left
> floating, any line pulled low drags the rail — and with it the *other two
> lines* — through the resistor network, overpowering the SoC's weak internal
> pull-ups. Symptom: all three inputs toggle in perfect lockstep. A **bare
> EC11** has no such network and genuinely needs no supply: 3-leg side
> A→CLK / middle→GND / B→DT, 2-leg side one→SW other→GND.

Smoke-test a (replacement) encoder without touching the display:

```bash
.venv/bin/python -m radiowall.input.encoder   # prints CW/CCW/PRESS; Ctrl+C
```

The driver debounces the switch and adds a **rotation guard** (the debounce
timer resets while turning) so electrical coupling can't fake a press.

> **Gotcha:** a cheap/worn KY-040 can emit *real* switch closures while you
> turn it — the shaft mechanically tickles its own button. No software filter
> fixes that; swap the encoder. Rotation reading is unaffected. (We burned a
> while on this with one bad unit — reseating wires and gentle turning ruled
> out connection/coupling; it was the encoder.)

The two ST7789 HAT buttons are on GPIO 23/24 (handled in `main.py`). The 55" IR
touch frame is USB and appears as `/dev/input/eventN` (evdev) — not yet wired in.

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

> **Do the first boot over Ethernet, not WiFi.** The Pi 3 B+'s built-in WiFi is
> too weak/flaky to survive the DietPi first-run install — it stalls on the
> internet-connectivity check (`ping 9.9.9.9` fails) and never finishes, leaving
> you stuck on temporary Dropbear with no `python3`. Plug in a cable and set, in
> `dietpi.txt`: `AUTO_SETUP_NET_ETHERNET_ENABLED=1` and
> `AUTO_SETUP_NET_WIFI_ENABLED=0`. Switch to WiFi later from inside if you want.
>
> Also note: **`dietpi.txt` is only read on the *first* boot.** If you need to
> change network settings after that, the reliable fix is to **re-flash** — just
> editing the file and rebooting won't re-apply it.

1. Flash DietPi image to the microSD.
2. Edit `dietpi.txt` on the boot partition: set `AUTO_SETUP_NET_ETHERNET_ENABLED=1`, `AUTO_SETUP_NET_WIFI_ENABLED=0`, a hostname (e.g. `radiowall`), `AUTO_SETUP_SSH_SERVER_INDEX=-2` (OpenSSH), and `AUTO_SETUP_AUTOMATED=1`. (For WiFi instead, fill in `dietpi-wifi.txt` — but see the warning above.)
3. Boot — self-install takes ~5–10 min and reboots itself once or twice.
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
apt install -y git python3 python3-pip python3-venv \
    python3-pygame python3-pil python3-yaml python3-requests python3-evdev \
    python3-rpi-lgpio python3-spidev ffmpeg
```

Three of those are easy to forget and each fails in a confusing way later:
- **`python3-rpi-lgpio`** — luma needs an `RPi.GPIO`-compatible module to drive
  the display's DC/backlight pins. On Trixie use the **lgpio-backed** shim, not
  classic `python3-rpi.gpio` (they conflict; the classic one misbehaves on
  recent kernels). Without it, display init throws.
- **`python3-spidev`** — the SPI transport luma uses. Missing → `No module named spidev`.
- **`ffmpeg`** — the audio decoder shells out to it for the visualizer. Missing
  is non-fatal (the app logs a warning and runs without the visualizer).

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

Or non-interactively — append `dtparam=spi=on` to the firmware config. **On
Trixie this is `/boot/firmware/config.txt`, not `/boot/config.txt`:**

```bash
grep -q '^dtparam=spi=on' /boot/firmware/config.txt || echo 'dtparam=spi=on' >> /boot/firmware/config.txt
reboot
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

### 9. Autostart on boot (systemd)

Run it as a managed service so it starts on boot and restarts on crash.
Per-device settings (flip, fonts, stream URL, mirror) go in `/etc/radiowall.env`:

```bash
cp config.example.env /etc/radiowall.env       # then edit
sudo cp systemd/radiowall.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now radiowall
journalctl -u radiowall -f                      # live logs
```

The unit's `EnvironmentFile=-/etc/radiowall.env` is optional (the `-` prefix),
and the default paths assume a root install at `/root/RadioWall/linux` — adjust
`WorkingDirectory`/`ExecStart`/`User` if you cloned elsewhere.

## Pitfalls we hit (and how to spot them)

| Symptom | Likely cause | Fix |
|---|---|---|
| Everything "feels slow" — apt, pip, SSH | **Under-volt throttling** (`vcgencmd get_throttled` non-zero) | Proper 5.1 V/2.5 A PSU + thick cable |
| VS Code Remote-SSH crashes the window | Pi is OOM — VS Code server + pip = too much on 1 GB | Don't use Remote-SSH on Pi 3 B+; edit on dev machine, `git push`/`pull` to deploy |
| `pip install` compiles for 10+ min | No prebuilt arm64 wheel for your Python version | Install the `python3-X` apt package; use `venv --system-site-packages` |
| `pip install` fails on `evdev` with "linux/input.h missing" | `evdev` needs kernel headers to compile | `apt install python3-evdev` (not `linux-headers`) |
| `/dev/spidev0.*` missing after enabling SPI | Module not loaded yet | `reboot`, then check `lsmod | grep spi` |
| Pi unreachable after plugging in HAT | Misaligned header (shorted rails) or under-volt when display draws current | Power off, reseat HAT on correct pins (1–26), re-check PSU |
| First-run install never finishes; stuck on Dropbear, no `python3` | DietPi's connectivity check failing over flaky WiFi | Do the first boot on **Ethernet** (see warning above); re-flash with `AUTO_SETUP_NET_ETHERNET_ENABLED=1` |
| Edited `dietpi.txt` but the change didn't apply | It's only read on the *first* boot | **Re-flash** to re-apply network/automation settings |
| Display init throws on `RPi.GPIO` / `No module named RPi` | luma's GPIO backend missing on Trixie | `apt install python3-rpi-lgpio` (lgpio-backed, **not** classic `python3-rpi.gpio`) |
| Display init throws `No module named spidev` | SPI Python transport missing | `apt install python3-spidev` |
| Visualizer flat / `ffmpeg not installed; decoder disabled` | no ffmpeg | `apt install ffmpeg`, then restart the service |
| Screen upside down | depends how the panel sits | set `RADIOWALL_FLIP=1` (in `/etc/radiowall.env`) |

## Orange Pi Zero 3W (A733) setup — working 2026-07-12

Board profiles live in `radiowall/hw/board.py` — auto-detected from
`/proc/device-tree/model` ("Raspberry Pi …" → `pi`; "sun60iw2" → `opizero3w`),
override with `RADIOWALL_BOARD=pi|opizero3w`. On non-Pi boards GPIO goes
through `radiowall/hw/gpio_compat.py`, an RPi.GPIO-compatible facade over
libgpiod v2 (pip `gpiod`), so the encoder and luma both work unchanged.

**The 40-pin header matches the Pi layout** for everything we use — SPI at
physical 19/23/24, UART at 8/10, I2C at 3/5 — so the ST7789 HAT and the
encoder plug in at the same physical positions. Only the numbers behind
them differ (see the table in `radiowall/hw/board.py`).

Setup on the official Orange Pi **Ubuntu Jammy server** image (Python 3.10,
kernel 6.6.x-sun60iw2 — DietPi/Armbian do NOT support the A733):

```bash
# 1. switch the Chinese default mirrors to ports.ubuntu.com (see git log)
# 2. enable SPI3 (→ /dev/spidev3.0/.1 after reboot):
echo 'overlays=spi3-cs0-cs1-spidev' | sudo tee -a /boot/orangepiEnv.txt && sudo reboot
# 3. deps + venv:
sudo apt install -y gcc python3-dev python3-venv gpiod python3-libgpiod \
    libjpeg-dev zlib1g-dev libfreetype6-dev
python3 -m venv .venv && .venv/bin/pip install -e ".[pi]"
# 4. run (spidev + gpiochip are root-only on this image):
sudo .venv/bin/python -m radiowall
```

Gotchas collected the hard way:
- `/proc/device-tree/model` is just `sun60iw2` — no board name; detection
  keys off that SoC string.
- The vendor image's `orangepi` user needs a password for sudo; drop a
  NOPASSWD file in `/etc/sudoers.d/` for unattended deploys (dev only).
- I2C1 sits on physical pins 38/40 — the same pins the encoder uses. Don't
  enable the `i2c1` overlay while an encoder is wired there.
- **SSD1322 module (TZT 3.12" Ver 2.1, 16-pin)**: ships in parallel-bus
  mode! 4-wire SPI needs the solder jumpers set to **R5 + R8 populated,
  R6 + R7 empty** (BS1=0, BS0=0 — table on the silkscreen; ours shipped
  R6+R8 = dead panel, moved R6→R5 with a solder bridge, 2026-07-12).
  Wiring (module pin → OPi physical): 1 GND→20, 2 VCC→17 (3.3V!),
  4 D0/CLK→23, 5 D1/DIN→19, 14 D/C#→22, 15 RES#→15, 16 CS#→24.
  Unused bus pins (6–13) floating — works on our unit; ground them if a
  future unit misbehaves.

## Porting to another SBC

**Raspberry Pi family (4, 5, Zero 2 W)**: identical steps. Pi 5 is dramatically faster; Zero 2 W's 512 MB RAM will struggle even with swap — lean harder on apt, avoid pip from source.

**Other non-Broadcom SBCs (Rock, etc.)**: add a `BoardProfile` in `radiowall/hw/board.py` (SPI port/device + GPIO line offsets for DC/backlight/encoder, chip path) — the gpiod shim handles the rest. Check the 40-pin layout before assuming the HAT plugs in.

## Layout

```
linux/
├── PLAN.md              ← master plan, build order, design decisions
├── README.md            ← this file
├── config.example.env   ← runtime settings template → /etc/radiowall.env
├── pyproject.toml
├── systemd/
│   └── radiowall.service
└── radiowall/
    ├── main.py          ← entry point: mockup + visualizer loop, buttons
    ├── logging_setup.py
    ├── config.py        ← persistent config store (setup UI writes it)
    ├── discovery.py     ← WiiM/LinkPlay SSDP discovery
    ├── wifi.py          ← nmcli scan/connect wrappers
    ├── display/
    │   ├── factory.py   ← picks emulator / st7789 / ssd1322 by env
    │   ├── fonts.py     ← height-relative, env-tunable font sizes
    │   ├── setup_ui.py  ← on-device setup: speaker / WiFi / calibration
    │   ├── visualizer.py← vfd / bars / mirror / radial / wave / scope / waterfall / vu
    │   └── mirror.py    ← broadcast frames to the LAN viewer
    ├── audio/
    │   ├── hub.py       ← fetch upstream stream once, fan out
    │   ├── proxy.py     ← re-serve to the WiiM at :8000
    │   └── decoder.py   ← ffmpeg → PCM → FFT for the visualizer
    └── tools/
        ├── display_mirror.py  ← laptop-side frame viewer
        └── udp_log_listen.py  ← laptop-side log viewer
```

Still to come (held until final hardware is wired): Radio.garden, LinkPlay,
`places.bin` lookup, evdev touch/encoder input, the state machine — see PLAN.md
build order.
