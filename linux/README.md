# RadioWall — Linux port

See [PLAN.md](PLAN.md) for the full plan and Build Order.

## Current state

Running on real hardware: a **Raspberry Pi 3 B+ / DietPi (Trixie)** drives a
1.14" 240×135 **ST7789** TFT showing the VFD-style "now playing" mockup plus
four audio-reactive visualizers (cycle with button A). An HTTP proxy re-serves
the chosen stream to the WiiM at `:8000/stream.mp3` while a local ffmpeg→FFT
path feeds the visualizer. Runs under **systemd** (autostart on boot); settings
live in `/etc/radiowall.env`.

Not yet ported from the ESP32 firmware: the actual radio logic (LinkPlay
client, Radio.garden client, `places.bin` nearest-city lookup, touch→city→play
state machine). The screen content is still a hardcoded mockup. See PLAN.md.

> **Platform note:** PLAN.md originally targeted an **Orange Pi Zero 3W**
> (Allwinner H618). It currently **won't boot** — diagnosis is blocked pending a
> **USB power tester** (rule out a weak-supply/brown-out) and a **CP2102
> USB-to-TTL adapter** (to get a serial boot console and see where it dies),
> both on order. Development moved to the Raspberry Pi 3 B+ to keep progress
> going. The Orange Pi is **parked, not abandoned** — the Python code is
> board-agnostic, so it can move back once the boot issue is sorted (expect
> different SPI device numbering and GPIO pinouts; see "Porting to another SBC").

## Parts list

| Role | Part |
|---|---|
| Compute | Raspberry Pi 3 B+ (1 GB) + microSD + **5.1 V / 2.5 A** PSU |
| Dev display | 1.14" 240×135 ST7789 "Pi TFT" (Adafruit Mini PiTFT or clone, 2 buttons) |
| Target display | TZT 3.12" 256×64 **SSD1322** SPI OLED |
| Inputs | EC11 rotary encoders · momentary buttons · 55" IR touch frame (USB) |
| Speaker | WiiM Amp Pro (`192.168.0.33`) — streams audio; the Pi only coordinates |
| Enclosure | Car-radio shell (planned) |

## Inputs (GPIO wiring)

**Rotary encoder (EC11 / KY-040)** — driver in `radiowall/input/encoder.py`.
Tested wiring on the Pi 3 B+ with the ST7789 HAT still attached (uses the spare
pins poking out past the HAT; `+` left unwired, internal pull-ups do the job):

| KY-040 | → Pi **physical pin** | BCM |
|---|---|---|
| CLK | 40 | GPIO21 |
| DT | 38 | GPIO20 |
| SW | 36 | GPIO16 |
| GND | 39 | — |
| + | *unwired* | — |

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
├── config.example.env   ← runtime settings template → /etc/radiowall.env
├── pyproject.toml
├── systemd/
│   └── radiowall.service
└── radiowall/
    ├── main.py          ← entry point: mockup + visualizer loop, buttons
    ├── logging_setup.py
    ├── display/
    │   ├── factory.py   ← picks emulator / st7789 / ssd1322 by env
    │   ├── fonts.py     ← height-relative, env-tunable font sizes
    │   ├── visualizer.py← bars / mirror / radial / wave
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
