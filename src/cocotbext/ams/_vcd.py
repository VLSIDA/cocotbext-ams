# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, Matthew Guthaus
# See LICENSE for details.

"""VCD writer for mixed-signal waveforms.

Generates a VCD file containing both:
- ``$var real`` signals for analog node voltages (continuous traces)
- ``$var wire`` signals for digitized output pins (binary 0/1)

This lets you view the analog internals and digital outputs together
in Surfer, GTKWave, or any viewer that supports real-valued VCD signals.
"""

from __future__ import annotations

import io
from pathlib import Path


class AnalogVcdWriter:
    """Writes mixed real-valued and digital signals to a VCD file.

    Usage::

        w = AnalogVcdWriter("mixed.vcd")
        w.register_signal("vout")          # real-valued analog node
        w.register_digital_signal("dout", width=4)  # digital output
        w.open()
        w.write_header()
        w.write_values(0.0, {"vout": 0.0}, {"dout": 0})
        w.write_values(1e-9, {"vout": 1.2}, {"dout": 5})
        w.close()
    """

    def __init__(
        self,
        path: str | Path,
        timescale: str = "1ps",
        scope: str = "analog",
    ) -> None:
        self._path = Path(path)
        self._timescale = timescale
        self._scope = scope
        # Real-valued (analog) signals: name -> vcd_id
        self._signals: dict[str, str] = {}
        # Digital signals: name -> (vcd_id, width)
        self._digital_signals: dict[str, tuple[str, int]] = {}
        self._prev_values: dict[str, float] = {}
        self._prev_digital: dict[str, int] = {}
        self._file: io.TextIOWrapper | None = None
        self._header_written = False
        self._last_time_ps: int = -1
        self._id_counter = 0

    def register_signal(self, name: str) -> None:
        """Register a real-valued (analog) signal.

        Must be called before :meth:`write_header`.
        """
        if name not in self._signals:
            self._signals[name] = self._make_id(self._id_counter)
            self._id_counter += 1

    def register_digital_signal(self, name: str, width: int = 1) -> None:
        """Register a digital (binary) signal.

        Args:
            name: Signal name.
            width: Bit width of the signal.

        Must be called before :meth:`write_header`.
        """
        if name not in self._digital_signals:
            self._digital_signals[name] = (self._make_id(self._id_counter), width)
            self._id_counter += 1

    def open(self) -> None:
        """Open the VCD file for writing."""
        self._file = open(self._path, "w")

    def write_header(self) -> None:
        """Write the VCD header with timescale, scope, and variable declarations."""
        if self._file is None:
            raise RuntimeError("VCD file not open")
        f = self._file
        f.write(f"$timescale {self._timescale} $end\n")
        f.write(f"$scope module {self._scope} $end\n")
        for name, vid in self._signals.items():
            f.write(f"$var real 64 {vid} {name} $end\n")
        for name, (vid, width) in self._digital_signals.items():
            f.write(f"$var wire {width} {vid} {name} $end\n")
        f.write("$upscope $end\n")
        f.write("$enddefinitions $end\n")
        self._header_written = True

    def write_values(
        self,
        time_sec: float,
        analog_values: dict[str, float] | None = None,
        digital_values: dict[str, int] | None = None,
    ) -> None:
        """Write signal values at the given simulation time.

        Only values that have actually changed since the last write are
        emitted, keeping the file compact.

        Args:
            time_sec: Simulation time in seconds.
            analog_values: Mapping of real signal name to voltage.
                Unregistered names are silently ignored.
            digital_values: Mapping of digital signal name to integer value.
                Unregistered names are silently ignored.
        """
        if not self._header_written or self._file is None:
            return

        time_ps = int(time_sec * 1e12)

        # Collect changed analog values
        changed_analog: dict[str, float] = {}
        if analog_values:
            for name, val in analog_values.items():
                if name in self._signals:
                    prev = self._prev_values.get(name)
                    if prev is None or val != prev:
                        changed_analog[name] = val
                        self._prev_values[name] = val

        # Collect changed digital values
        changed_digital: dict[str, int] = {}
        if digital_values:
            for name, val in digital_values.items():
                if name in self._digital_signals:
                    prev = self._prev_digital.get(name)
                    if prev is None or val != prev:
                        changed_digital[name] = val
                        self._prev_digital[name] = val

        if not changed_analog and not changed_digital:
            return

        if time_ps != self._last_time_ps:
            self._file.write(f"#{time_ps}\n")
            self._last_time_ps = time_ps

        for name, val in changed_analog.items():
            vid = self._signals[name]
            self._file.write(f"r{val:.15g} {vid}\n")

        for name, val in changed_digital.items():
            vid, width = self._digital_signals[name]
            if width == 1:
                self._file.write(f"{val & 1}{vid}\n")
            else:
                bits = format(val & ((1 << width) - 1), f"0{width}b")
                self._file.write(f"b{bits} {vid}\n")

    def close(self) -> None:
        """Flush and close the VCD file."""
        if self._file is not None:
            self._file.close()
            self._file = None

    @staticmethod
    def _make_id(n: int) -> str:
        """Generate a VCD identifier from an index.

        VCD identifiers use printable ASCII characters from ``!`` (33)
        to ``~`` (126), giving 94 single-char IDs before needing
        multi-character identifiers.
        """
        chars: list[str] = []
        while True:
            chars.append(chr(33 + (n % 94)))
            n //= 94
            if n == 0:
                break
        return "".join(chars)
