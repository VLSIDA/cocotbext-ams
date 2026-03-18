"""DigitalPin dataclass for configuring digital-analog signal mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class DigitalPin:
    """Configuration for a single digital pin on an analog block.

    Args:
        direction: Pin direction from the analog block's perspective.
            "input" means digital drives analog (Verilog -> SPICE).
            "output" means analog drives digital (SPICE -> Verilog).
        width: Bit width of the pin (each bit gets its own SPICE source/probe).
        vdd: Logic-high voltage level.
        vss: Logic-low voltage level.
        threshold: Voltage threshold for analog-to-digital conversion.
            Defaults to midpoint (vdd + vss) / 2.
    """

    direction: Literal["input", "output"]
    width: int = 1
    vdd: float = 1.8
    vss: float = 0.0
    threshold: float | None = None

    def _effective_threshold(self) -> float:
        return self.threshold if self.threshold is not None else (self.vdd + self.vss) / 2

    def digital_to_analog(self, value: int) -> list[float]:
        """Convert an integer value to a list of voltages, one per bit (LSB first)."""
        voltages = []
        for bit in range(self.width):
            if (value >> bit) & 1:
                voltages.append(self.vdd)
            else:
                voltages.append(self.vss)
        return voltages

    def analog_to_digital(self, voltages: list[float]) -> int:
        """Convert a list of voltages (LSB first) to an integer value."""
        threshold = self._effective_threshold()
        value = 0
        for bit, v in enumerate(voltages):
            if v >= threshold:
                value |= 1 << bit
        return value
