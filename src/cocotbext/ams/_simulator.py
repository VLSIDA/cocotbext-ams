# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, Matthew Guthaus
# See LICENSE for details.

"""Abstract base class for analog simulator interfaces."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Any

log = logging.getLogger(__name__)


class SimulatorInterface(ABC):
    """Base class for analog simulator backends (ngspice, Xyce, etc.).

    Provides shared state for data exchange, crossing detection, VCD
    recording, and synchronization.  Subclasses implement the simulator-
    specific ctypes wrapper and control flow.
    """

    def __init__(self) -> None:
        # Data exchange dictionaries
        self._vsrc_values: dict[str, float] = {}
        self._node_voltages: dict[str, float] = {}

        # Sync state
        self._next_sync_time: float = 0.0
        self._spice_time: float = 0.0
        self._simulation_done = False

        # Callback invoked at each sync point — set by the bridge.
        # Signature: () -> None.  Called from the simulator thread; expected
        # to be a @resume-decorated function that blocks until cocotb is done.
        self._on_sync_point: Any = None

        # Crossing detection state
        self._crossing_detected: bool = False
        self._prev_digital_values: dict[str, int] = {}
        # Registered by bridge: pin_name -> (node_names, DigitalPin)
        self._output_pin_configs: dict[str, tuple[list[str], Any]] = {}

        # Analog VCD writer — set by bridge when analog_vcd is requested
        self._vcd_writer: Any = None

        # Error tracking
        self._error: Exception | None = None

        # Event signaled when simulator pauses
        self._sim_paused = threading.Event()

    def _check_crossings(self) -> None:
        """Check output pins for threshold crossings after voltage update."""
        for pin_name, (node_names, pin) in self._output_pin_configs.items():
            voltages = [self._node_voltages.get(n, 0.0) for n in node_names]
            prev_val = self._prev_digital_values.get(pin_name)
            new_val = pin.analog_to_digital(voltages, prev_value=prev_val)
            if prev_val is not None and new_val != prev_val:
                self._crossing_detected = True
                log.debug(
                    "Threshold crossing: %s %d->%d at t=%.3fus (v=%s)",
                    pin_name, prev_val, new_val,
                    self._spice_time * 1e6,
                    ", ".join(f"{v:.3f}" for v in voltages),
                )
            self._prev_digital_values[pin_name] = new_val

    def _write_vcd(self, sim_time: float) -> None:
        """Write VCD data if a writer is attached."""
        if self._vcd_writer is not None:
            self._vcd_writer.write_values(
                sim_time,
                analog_values=self._node_voltages,
                digital_values=self._prev_digital_values,
            )

    @abstractmethod
    def load_circuit(self, lines: list[str]) -> None:
        """Load a circuit from netlist lines."""

    @abstractmethod
    def run_simulation(self, tran_step: str, tran_stop: str) -> None:
        """Run a transient simulation."""

    @abstractmethod
    def get_node_voltage(self, node: str) -> float:
        """Get a node voltage."""

    @abstractmethod
    def set_vsrc(self, name: str, value: float) -> None:
        """Set the value of a voltage source."""

    @abstractmethod
    def halt(self) -> None:
        """Halt a running simulation."""

    @abstractmethod
    def reset(self) -> None:
        """Reset simulator state."""

    @abstractmethod
    def is_running(self) -> bool:
        """Check if the simulator is still running."""
