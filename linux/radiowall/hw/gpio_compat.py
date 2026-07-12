"""RPi.GPIO-compatible facade over libgpiod v2 (pip package `gpiod`).

Implements exactly the subset RadioWall's consumers use — the encoder
(`setmode/setwarnings/setup(IN, pull_up_down)/input/cleanup`) and
luma.core's SPI interface + luma.lcd's backlight (`setup(OUT)/output`).
Pin numbers are line offsets on the chip passed to the constructor
(e.g. 96 = PD0 on the A733's /dev/gpiochip0).

Not implemented (nothing here needs them): edge detection callbacks,
PWM, BOARD numbering (setmode is accepted and ignored).
"""

from __future__ import annotations

import gpiod
from gpiod.line import Bias, Direction, Value


class GpiodGPIO:
    # RPi.GPIO API constants. Numbering modes are accepted but
    # meaningless here — pins are always chip line offsets.
    BCM = 11
    BOARD = 10
    IN = 1
    OUT = 0
    HIGH = 1
    LOW = 0
    PUD_OFF = 20
    PUD_DOWN = 21
    PUD_UP = 22

    def __init__(self, chip_path: str = "/dev/gpiochip0") -> None:
        self._chip_path = chip_path
        self._requests: dict[int, gpiod.LineRequest] = {}
        # Opening the chip validates the path/permissions early, so
        # get_gpio() can fall back cleanly instead of dying later.
        with gpiod.Chip(chip_path):
            pass

    def setmode(self, mode) -> None:  # noqa: ARG002
        pass

    def setwarnings(self, flag) -> None:  # noqa: ARG002
        pass

    def setup(self, channel, direction, pull_up_down=PUD_OFF, initial=None):
        pins = channel if isinstance(channel, (list, tuple)) else [channel]
        if direction == self.IN:
            bias = {
                self.PUD_UP: Bias.PULL_UP,
                self.PUD_DOWN: Bias.PULL_DOWN,
            }.get(pull_up_down, Bias.DISABLED)
            settings = gpiod.LineSettings(direction=Direction.INPUT, bias=bias)
        else:
            value = Value.ACTIVE if initial == self.HIGH else Value.INACTIVE
            settings = gpiod.LineSettings(
                direction=Direction.OUTPUT, output_value=value)
        for pin in pins:
            old = self._requests.pop(pin, None)
            if old is not None:
                old.release()
            self._requests[pin] = gpiod.request_lines(
                self._chip_path,
                consumer="radiowall",
                config={pin: settings},
            )

    def input(self, channel: int) -> int:
        return 1 if self._requests[channel].get_value(channel) == Value.ACTIVE else 0

    def output(self, channel, value) -> None:
        pins = channel if isinstance(channel, (list, tuple)) else [channel]
        values = value if isinstance(value, (list, tuple)) else [value] * len(pins)
        for pin, val in zip(pins, values):
            self._requests[pin].set_value(
                pin, Value.ACTIVE if val else Value.INACTIVE)

    def cleanup(self, channel=None) -> None:
        if channel is None:
            pins = list(self._requests)
        else:
            pins = channel if isinstance(channel, (list, tuple)) else [channel]
        for pin in pins:
            req = self._requests.pop(pin, None)
            if req is not None:
                req.release()
