# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, Matthew Guthaus
# See LICENSE for details.

"""ctypes wrapper for Xyce (XyceCInterface) shared library.

Xyce uses an explicit-stepping model: the caller drives time via
``xyce_simulateUntil(time)`` and reads/updates state between steps.
This is fundamentally different from ngspice's callback-driven model,
but from the bridge's perspective both look identical — they run in a
``@bridge`` thread and periodically call ``_on_sync_point()``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import tempfile
from pathlib import Path
from cocotbext.ams._simulator import SimulatorInterface

log = logging.getLogger(__name__)


def _find_libxyce(hint: str | Path | None = None) -> str:
    """Locate libxycecinterface.so, trying hint path first, then system search."""
    if hint is not None:
        p = Path(hint)
        if p.is_file():
            return str(p)
        if p.is_dir():
            for pattern in ("libxycecinterface*.so*", "libxycecinterface*.dylib*"):
                for candidate in sorted(p.glob(pattern)):
                    return str(candidate)
        raise FileNotFoundError(f"Cannot find libxycecinterface at: {hint}")

    found = ctypes.util.find_library("xycecinterface")
    if found:
        return found

    raise FileNotFoundError(
        "Cannot find libxycecinterface shared library.\n"
        "Install Xyce with shared library support, or pass the library "
        "path explicitly via simulator_lib='...'."
    )


def _parse_spice_time(time_str: str) -> float:
    """Parse a SPICE time string (e.g., '100n', '1u', '0.5m') to seconds."""
    suffixes = {
        "t": 1e-12, "p": 1e-12,
        "n": 1e-9,
        "u": 1e-6,
        "m": 1e-3,
        "s": 1.0,
    }
    time_str = time_str.strip().lower()
    for suffix, scale in suffixes.items():
        if time_str.endswith(suffix):
            return float(time_str[:-len(suffix)]) * scale
    return float(time_str)


class XyceInterface(SimulatorInterface):
    """Wrapper around Xyce's C interface (XyceCInterface) via ctypes.

    Unlike ngspice, Xyce does not use callbacks. Instead, the caller
    drives the simulation forward via ``xyce_simulateUntil()`` and
    explicitly reads node voltages and updates sources between steps.

    Crossing detection occurs at ``simulateUntil()`` step boundaries.
    This is coarser than ngspice's per-substep detection but acceptable
    for most use cases.
    """

    def __init__(self, lib_path: str | Path | None = None) -> None:
        super().__init__()
        self._lib_path = _find_libxyce(lib_path)
        self._lib = ctypes.CDLL(self._lib_path)
        self._xyce_ptr: ctypes.c_void_p | None = None
        self._netlist_path: str | None = None
        self._output_nodes: list[str] = []

        self._setup_signatures()

    def _setup_signatures(self) -> None:
        """Set up ctypes function signatures for Xyce C interface."""
        # void* xyce_open(int argc, char** argv)
        self._lib.xyce_open.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self._lib.xyce_open.restype = ctypes.c_int

        # int xyce_close(void* ptr)
        self._lib.xyce_close.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self._lib.xyce_close.restype = ctypes.c_int

        # int xyce_initialize(void** ptr, int argc, char** argv)
        self._lib.xyce_initialize.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_char_p),
        ]
        self._lib.xyce_initialize.restype = ctypes.c_int

        # int xyce_simulateUntil(void* ptr, double time, double* actual_time)
        self._lib.xyce_simulateUntil.argtypes = [
            ctypes.c_void_p,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
        ]
        self._lib.xyce_simulateUntil.restype = ctypes.c_int

        # int xyce_obtainResponse(void* ptr, const char* name, double* value)
        self._lib.xyce_obtainResponse.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_double),
        ]
        self._lib.xyce_obtainResponse.restype = ctypes.c_int

        # int xyce_updateTimeVoltagePairs(void* ptr, const char* name,
        #     int num_points, double* times, double* voltages)
        self._lib.xyce_updateTimeVoltagePairs.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        self._lib.xyce_updateTimeVoltagePairs.restype = ctypes.c_int

    def load_circuit(self, lines: list[str]) -> None:
        """Write the netlist to a temp file and initialize Xyce."""
        # Write netlist to a temporary file (Xyce reads from file)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cir", delete=False,
        ) as f:
            f.write("\n".join(lines) + "\n")
            self._netlist_path = f.name

        # Collect output node names from .PRINT TRAN directives
        self._output_nodes = []
        for line in lines:
            stripped = line.strip().upper()
            if stripped.startswith(".PRINT TRAN"):
                # Parse node names from ".PRINT TRAN v(node1) v(node2) ..."
                tokens = line.strip().split()[2:]  # skip ".PRINT" and "TRAN"
                for token in tokens:
                    self._output_nodes.append(token)

        # Initialize Xyce with the netlist file
        self._xyce_ptr = ctypes.c_void_p()
        argv = (ctypes.c_char_p * 2)(
            b"Xyce",
            self._netlist_path.encode("utf-8"),
        )
        ret = self._lib.xyce_initialize(
            ctypes.byref(self._xyce_ptr),
            2,
            argv,
        )
        if ret != 1:
            raise RuntimeError(f"xyce_initialize failed with code {ret}")

    def run_simulation(self, tran_step: str, tran_stop: str) -> None:
        """Run transient simulation via explicit stepping loop.

        Steps Xyce forward by ``_next_sync_time`` intervals, updating
        sources and reading voltages at each step boundary.
        """
        if self._xyce_ptr is None:
            raise RuntimeError("No circuit loaded — call load_circuit() first")

        stop_time = _parse_spice_time(tran_stop)
        step_time = _parse_spice_time(tran_step)
        actual_time = ctypes.c_double(0.0)

        while not self._simulation_done:
            # Determine the next time to step to
            target_time = self._next_sync_time
            if target_time > stop_time:
                target_time = stop_time

            # Push current VSRC values to Xyce
            self._update_sources()

            # Step simulation forward
            ret = self._lib.xyce_simulateUntil(
                self._xyce_ptr,
                ctypes.c_double(target_time),
                ctypes.byref(actual_time),
            )

            self._spice_time = actual_time.value

            if ret == 0:
                # Simulation completed (reached end)
                self._simulation_done = True
                self._read_voltages()
                self._check_crossings()
                self._write_vcd(self._spice_time)
                self._sim_paused.set()
                break

            if ret != 1:
                self._error = RuntimeError(
                    f"xyce_simulateUntil failed with code {ret}"
                )
                self._simulation_done = True
                self._sim_paused.set()
                break

            # Read node voltages from Xyce
            self._read_voltages()

            # Check for threshold crossings
            self._check_crossings()

            # Write VCD data
            self._write_vcd(self._spice_time)

            # If we've reached a sync point, hand control to cocotb
            if actual_time.value >= self._next_sync_time - step_time * 0.01:
                if self._on_sync_point is not None:
                    self._on_sync_point()

            if self._spice_time >= stop_time:
                self._simulation_done = True
                self._sim_paused.set()
                break

    def _update_sources(self) -> None:
        """Push current VSRC values to Xyce via xyce_updateTimeVoltagePairs."""
        if self._xyce_ptr is None:
            return
        for name, voltage in self._vsrc_values.items():
            time_arr = (ctypes.c_double * 1)(self._spice_time)
            volt_arr = (ctypes.c_double * 1)(voltage)
            self._lib.xyce_updateTimeVoltagePairs(
                self._xyce_ptr,
                name.encode("utf-8"),
                1,
                time_arr,
                volt_arr,
            )

    def _read_voltages(self) -> None:
        """Read node voltages from Xyce via xyce_obtainResponse."""
        if self._xyce_ptr is None:
            return
        for node_expr in self._output_nodes:
            value = ctypes.c_double(0.0)
            ret = self._lib.xyce_obtainResponse(
                self._xyce_ptr,
                node_expr.encode("utf-8"),
                ctypes.byref(value),
            )
            if ret == 1:
                # Store under original expression and bare node name
                self._node_voltages[node_expr] = value.value
                self._node_voltages[node_expr.lower()] = value.value
                # Strip v() wrapper
                lower = node_expr.lower()
                if lower.startswith("v(") and lower.endswith(")"):
                    bare = lower[2:-1]
                    self._node_voltages[bare] = value.value

    def get_node_voltage(self, node: str) -> float:
        """Get a node voltage from the cached values."""
        return self._node_voltages.get(node, 0.0)

    def set_vsrc(self, name: str, value: float) -> None:
        """Set the value of a voltage source."""
        self._vsrc_values[name] = value

    def halt(self) -> None:
        """Halt a running simulation."""
        self._simulation_done = True

    def reset(self) -> None:
        """Reset simulator state."""
        self._node_voltages.clear()
        self._vsrc_values.clear()
        self._simulation_done = False
        self._error = None

    def is_running(self) -> bool:
        """Check if the simulation is still running."""
        return not self._simulation_done

    def close(self) -> None:
        """Close the Xyce instance and clean up."""
        if self._xyce_ptr is not None:
            self._lib.xyce_close(ctypes.byref(self._xyce_ptr))
            self._xyce_ptr = None
