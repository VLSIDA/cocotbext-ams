# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, Matthew Guthaus
# See LICENSE for details.

"""MixedSignalBridge: event-driven co-simulation orchestrator.

Coordinates co-simulation between cocotb (digital) and an analog SPICE
simulator (ngspice or Xyce).  Synchronization is event-driven: threshold
crossings on analog outputs trigger immediate sync, while a configurable
maximum interval provides a fallback ceiling. Digital-to-analog updates
happen asynchronously via ValueChange monitors — no sync overhead.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cocotb
from cocotb._bridge import bridge, resume
from cocotb.handle import Force, Release
from cocotb.triggers import Timer, ValueChange

from cocotbext.ams._netlist import (
    generate_netlist,
    get_output_node_names,
    get_vsrc_names,
)
from cocotbext.ams._ngspice import NgspiceInterface
from cocotbext.ams._pins import DigitalPin
from cocotbext.ams._simulator import SimulatorInterface
from cocotbext.ams._vcd import AnalogVcdWriter

log = logging.getLogger(__name__)


@dataclass
class AnalogBlock:
    """Description of an analog block to be co-simulated.

    Args:
        name: Instance name (must match the Verilog stub module instance path).
        spice_file: Path to the SPICE netlist containing the subcircuit.
        subcircuit: Name of the .subckt in the SPICE file.
        digital_pins: Mapping of pin name -> DigitalPin configuration.
        analog_inputs: Mapping of analog input name -> initial voltage.
            These use EXTERNAL sources so they can be changed at runtime
            via set_analog_input().
        vdd: Supply voltage.
        vss: Ground voltage.
        tran_step: Transient analysis internal step size.
        extra_lines: Additional SPICE lines to include in the generated
            netlist (e.g., ``.include`` directives for PDK libraries).
        simulator: Simulator backend — ``"ngspice"`` (default) or ``"xyce"``.
    """

    name: str
    spice_file: str | Path
    subcircuit: str
    digital_pins: dict[str, DigitalPin] = field(default_factory=dict)
    analog_inputs: dict[str, float] = field(default_factory=dict)
    vdd: float = 1.8
    vss: float = 0.0
    tran_step: str = "0.1n"
    extra_lines: list[str] = field(default_factory=list)
    simulator: str = "ngspice"


class MixedSignalBridge:
    """Orchestrates event-driven co-simulation between cocotb and a SPICE simulator.

    Synchronization is triggered by two mechanisms:
    1. **Event-driven:** When an analog output crosses a digital threshold,
       the simulator immediately syncs to update the Verilog signal.
    2. **Fallback interval:** A configurable maximum interval ensures sync
       happens even when no crossings occur, bounding time drift.

    Digital-to-analog updates (Verilog -> SPICE) happen asynchronously via
    ``ValueChange`` monitor coroutines that update the VSRC dict directly.

    Thread model:
        - The simulator runs a blocking simulation inside a ``@bridge`` thread.
        - At each sync point (event or fallback), the simulator thread calls
          a ``@resume`` function to block and let cocotb advance digital time.
        - For ngspice: the ``GetSyncData`` callback triggers sync.
        - For Xyce: the explicit ``simulateUntil`` stepping loop triggers sync.

    Thread safety:
        - ``_vsrc_values`` dict is written by cocotb coroutines (ValueChange
          monitors) and read by the simulator thread.
          This is safe because Python's GIL ensures dict reads/writes are
          atomic, and stale reads are acceptable.
        - ``_node_voltages`` dict is written by the simulator thread
          and read by cocotb (at sync points only, when the simulator is paused).
        - All other shared state is only accessed at sync points when one
          thread is blocked.

    Args:
        dut: cocotb DUT handle.
        analog_blocks: List of AnalogBlock descriptions.
        max_sync_interval_ns: Maximum time between sync points in nanoseconds.
            Sync also occurs immediately on any threshold crossing.
        simulator_lib: Path to the simulator shared library (auto-detected if None).
        ngspice_lib: Deprecated alias for simulator_lib.
    """

    def __init__(
        self,
        dut: Any,
        analog_blocks: list[AnalogBlock],
        max_sync_interval_ns: float | None = None,
        simulator_lib: str | Path | None = None,
        ngspice_lib: str | Path | None = None,
    ) -> None:
        # Handle deprecated ngspice_lib parameter
        if ngspice_lib is not None:
            if simulator_lib is not None:
                raise ValueError(
                    "Cannot specify both 'simulator_lib' and "
                    "'ngspice_lib' (deprecated alias)"
                )
            warnings.warn(
                "'ngspice_lib' is deprecated, use 'simulator_lib' instead",
                DeprecationWarning,
                stacklevel=2,
            )
            simulator_lib = ngspice_lib

        if max_sync_interval_ns is None:
            max_sync_interval_ns = 100.0

        self._dut = dut
        self._analog_blocks = analog_blocks
        self._max_sync_interval_ns = max_sync_interval_ns
        self._max_sync_interval_sec = max_sync_interval_ns * 1e-9
        self._simulator_lib = simulator_lib

        self._sim: SimulatorInterface | None = None
        self._running = False

        # Track SPICE time at last sync for dynamic Timer advance
        self._last_sync_spice_time: float = 0.0

        # Resolved handles and mappings (populated during start)
        self._block_vsrc_names: dict[str, dict[str, list[str]]] = {}
        self._block_output_nodes: dict[str, dict[str, list[str]]] = {}
        self._block_analog_vsrc_names: dict[str, dict[str, str]] = {}

    async def start(
        self,
        duration_ns: float,
        analog_vcd: str | Path | None = None,
        vcd_nodes: list[str] | None = None,
    ) -> None:
        """Start the mixed-signal co-simulation.

        Args:
            duration_ns: Total simulation duration in nanoseconds.
            analog_vcd: Path for a VCD file recording analog node voltages
                as ``real``-typed signals.  The VCD is written at full ngspice
                resolution (every accepted timestep) and can be loaded
                alongside the HDL simulator's digital VCD in Surfer, GTKWave,
                or any viewer that supports real-valued VCD signals.
                ``None`` (default) disables recording.
            vcd_nodes: Additional SPICE node names to record in the analog
                VCD.  Output pin nodes are always included automatically.
        """
        if self._running:
            raise RuntimeError("Bridge is already running")

        # Determine simulator type from the first block (all blocks must
        # use the same simulator in this implementation).
        simulator = self._analog_blocks[0].simulator if self._analog_blocks else "ngspice"

        sim = self._create_simulator(simulator)
        self._sim = sim
        self._running = True
        self._last_sync_spice_time = 0.0

        # Install the sync-point callback that bridges back into cocotb
        sim._on_sync_point = self._on_sync_point_resume

        # Collect VCD registration info: analog (real) nodes and digital (wire) pins
        vcd_analog_names: list[str] = []
        vcd_digital_pins: list[tuple[str, int]] = []  # (pin_name, width)

        # Load circuits for each analog block
        for block in self._analog_blocks:
            tran_stop = f"{duration_ns}n"
            netlist_lines = generate_netlist(
                spice_file=block.spice_file,
                subcircuit=block.subcircuit,
                digital_pins=block.digital_pins,
                analog_inputs=block.analog_inputs,
                vdd=block.vdd,
                vss=block.vss,
                tran_step=block.tran_step,
                tran_stop=tran_stop,
                extra_lines=block.extra_lines or None,
                simulator=block.simulator,
            )
            sim.load_circuit(netlist_lines)

            # Cache VSRC and output node name mappings
            self._block_vsrc_names[block.name] = get_vsrc_names(block.digital_pins)
            self._block_output_nodes[block.name] = get_output_node_names(block.digital_pins)

            # Register output pin configs for crossing detection
            output_nodes = self._block_output_nodes[block.name]
            for pin_name, pin in block.digital_pins.items():
                if pin.direction == "output":
                    node_names = output_nodes.get(pin_name, [])
                    if node_names:
                        sim._output_pin_configs[pin_name] = (node_names, pin)
                        # Analog nodes (real): the raw SPICE voltages
                        vcd_analog_names.extend(node_names)
                        # Digital signal (wire): the digitized output value
                        vcd_digital_pins.append((pin_name, pin.width))

            # Include analog input nodes in VCD (real-valued)
            for ain_name in block.analog_inputs:
                vcd_analog_names.append(ain_name)

            # Cache analog input VSRC names
            self._block_analog_vsrc_names[block.name] = {
                name: f"v_{name}" for name in block.analog_inputs
            }

            # Set initial analog input VSRC values
            for ain_name, voltage in block.analog_inputs.items():
                sim.set_vsrc(f"v_{ain_name}", voltage)

            # Set initial digital input VSRC values from Verilog signal states
            self._update_vsrc_from_digital(block)

            # Spawn ValueChange monitor coroutines for each input pin
            for pin_name, pin in block.digital_pins.items():
                if pin.direction == "input":
                    cocotb.start_soon(
                        self._monitor_digital_input(block, pin_name, pin)
                    )

        # Set up VCD writer if requested
        if analog_vcd is not None:
            if vcd_nodes:
                vcd_analog_names.extend(vcd_nodes)
            vcd_writer = AnalogVcdWriter(analog_vcd)
            # Register analog (real) signals for SPICE node voltages
            for name in dict.fromkeys(vcd_analog_names):
                vcd_writer.register_signal(name)
            # Register digital (wire) signals for digitized output pins
            for pin_name, width in vcd_digital_pins:
                vcd_writer.register_digital_signal(pin_name, width)
            vcd_writer.open()
            vcd_writer.write_header()
            sim._vcd_writer = vcd_writer

        # Set initial sync time
        sim._next_sync_time = self._max_sync_interval_sec

        log.info(
            "Starting mixed-signal co-simulation (%s): max_sync_interval=%.1fns, duration=%.1fns",
            simulator, self._max_sync_interval_ns, duration_ns,
        )

        # Run simulation in a @bridge thread.
        # The sync callback blocks the simulator thread and runs the signal
        # exchange + Timer advance in the cocotb scheduler.
        tran_step = self._analog_blocks[0].tran_step if self._analog_blocks else "0.1n"
        try:
            await self._run_simulation(tran_step, f"{duration_ns}n")
        finally:
            self._running = False
            # Close analog VCD file even if simulation threw an exception
            if sim._vcd_writer is not None:
                sim._vcd_writer.close()
                log.info("Analog VCD written to: %s", analog_vcd)

        log.info("Mixed-signal co-simulation finished")

    async def stop(self) -> None:
        """Stop the co-simulation and release all forced signals."""
        if not self._running:
            return

        self._running = False

        if self._sim is not None:
            if self._sim._vcd_writer is not None:
                self._sim._vcd_writer.close()
                self._sim._vcd_writer = None
            self._sim.halt()

        # Release all forced output signals
        for block in self._analog_blocks:
            self._release_outputs(block)

        log.info("Mixed-signal co-simulation stopped")

    def set_analog_input(self, block_name: str, input_name: str, voltage: float) -> None:
        """Change an analog input voltage at runtime.

        The new voltage takes effect at the next sync point.

        Args:
            block_name: Name of the analog block.
            input_name: Name of the analog input (as specified in analog_inputs).
            voltage: New voltage value.
        """
        if self._sim is None:
            raise RuntimeError("Bridge not started")

        ain_vsrc = self._block_analog_vsrc_names.get(block_name, {}).get(input_name)
        if ain_vsrc is None:
            raise KeyError(
                f"No analog input '{input_name}' on block '{block_name}'"
            )
        self._sim.set_vsrc(ain_vsrc, voltage)

    def get_analog_voltage(self, block_name: str, node: str) -> float:
        """Probe any SPICE node voltage.

        Args:
            block_name: Name of the analog block.
            node: SPICE node name (e.g., "d0", "ain").

        Returns:
            Latest voltage at the node.
        """
        if self._sim is None:
            raise RuntimeError("Bridge not started")
        return self._sim.get_node_voltage(node)

    # ------------------------------------------------------------------ #
    # Internal: simulator creation and thread via bridge/resume
    # ------------------------------------------------------------------ #

    def _create_simulator(self, simulator: str) -> SimulatorInterface:
        """Create the appropriate simulator interface."""
        if simulator == "ngspice":
            return NgspiceInterface(self._simulator_lib)
        elif simulator == "xyce":
            from cocotbext.ams._xyce import XyceInterface
            return XyceInterface(self._simulator_lib)
        else:
            raise ValueError(
                f"Unknown simulator: {simulator!r} (expected 'ngspice' or 'xyce')"
            )

    @bridge
    def _run_simulation(self, tran_step: str, tran_stop: str) -> None:
        """Run the simulator's transient analysis in a bridge thread.

        For ngspice: the GetSyncData callback triggers sync points.
        For Xyce: the explicit stepping loop triggers sync points.
        Both call the @resume function _on_sync_point_resume at each
        sync point.
        """
        assert self._sim is not None
        self._sim.run_simulation(tran_step, tran_stop)

    @resume
    async def _on_sync_point_resume(self) -> None:
        """Called from the simulator thread at each sync point.

        Sync points are triggered either by a threshold crossing (event-driven)
        or by the fallback interval ceiling. This @resume function runs in
        the cocotb scheduler context:
        1. Reads analog outputs and forces them onto Verilog signals.
        2. Advances digital simulation by the actual elapsed SPICE time.
        3. Advances _next_sync_time for the next fallback interval.
        """
        assert self._sim is not None

        if self._sim._error is not None:
            raise self._sim._error

        # Analog -> Digital: read SPICE outputs, force onto Verilog
        for block in self._analog_blocks:
            self._read_analog_outputs(block)

        # Advance digital simulation by actual elapsed time
        elapsed_sec = self._sim._spice_time - self._last_sync_spice_time
        elapsed_ns = elapsed_sec * 1e9
        if elapsed_ns > 0:
            await Timer(round(elapsed_ns * 1000), "ps")
        self._last_sync_spice_time = self._sim._spice_time

        # Advance fallback sync time
        self._sim._next_sync_time = (
            self._sim._spice_time + self._max_sync_interval_sec
        )

    # ------------------------------------------------------------------ #
    # Internal: digital-to-analog monitors
    # ------------------------------------------------------------------ #

    async def _monitor_digital_input(
        self, block: AnalogBlock, pin_name: str, pin: DigitalPin,
    ) -> None:
        """Monitor a Verilog input signal and update VSRC values on change.

        This coroutine uses ``await ValueChange(handle)`` to react to HDL
        signal changes with zero sync overhead — the updated VSRC dict is
        read by ngspice on its next internal evaluation step.
        """
        assert self._sim is not None
        vsrc_map = self._block_vsrc_names.get(block.name, {})
        vsrc_names = vsrc_map.get(pin_name, [])
        if not vsrc_names:
            return

        try:
            handle = self._resolve_signal(block.name, pin_name)
        except AttributeError:
            log.warning(
                "Cannot monitor input %s.%s -- handle not found",
                block.name, pin_name,
            )
            return

        log.debug("Monitoring input %s.%s for value changes", block.name, pin_name)
        while self._running:
            try:
                await ValueChange(handle)
            except Exception:
                # ValueChange may not be supported on all simulators;
                # fall back to letting sync points handle D→A updates.
                log.warning(
                    "ValueChange not available for %s.%s — "
                    "falling back to sync-point updates. Input changes "
                    "will only propagate at fallback sync intervals.",
                    block.name, pin_name,
                )
                return

            try:
                val = int(handle.value)
            except (AttributeError, ValueError):
                val = 0

            voltages = pin.digital_to_analog(val)
            for vsrc_name, voltage in zip(vsrc_names, voltages):
                self._sim.set_vsrc(vsrc_name, voltage)

    # ------------------------------------------------------------------ #
    # Internal: signal exchange
    # ------------------------------------------------------------------ #

    def _update_vsrc_from_digital(self, block: AnalogBlock) -> None:
        """Read Verilog input signals and update VSRC values."""
        assert self._sim is not None

        vsrc_map = self._block_vsrc_names.get(block.name, {})
        for pin_name, pin in block.digital_pins.items():
            if pin.direction != "input":
                continue

            vsrc_names = vsrc_map.get(pin_name, [])
            if not vsrc_names:
                continue

            # Get the Verilog signal value
            try:
                handle = self._resolve_signal(block.name, pin_name)
                val = int(handle.value)
            except (AttributeError, ValueError):
                val = 0  # default to 0 if signal is X/Z

            # Convert to analog voltages and set VSRC values
            voltages = pin.digital_to_analog(val)
            for vsrc_name, voltage in zip(vsrc_names, voltages):
                self._sim.set_vsrc(vsrc_name, voltage)

    def _read_analog_outputs(self, block: AnalogBlock) -> None:
        """Read simulator output node voltages and force onto Verilog signals."""
        assert self._sim is not None

        output_nodes = self._block_output_nodes.get(block.name, {})
        for pin_name, pin in block.digital_pins.items():
            if pin.direction != "output":
                continue

            node_names = output_nodes.get(pin_name, [])
            if not node_names:
                continue

            # Read voltages from ngspice
            voltages = []
            for node in node_names:
                v = self._sim.get_node_voltage(node)
                voltages.append(v)

            # Convert to digital value (use prev_value for hysteresis)
            prev_val = self._sim._prev_digital_values.get(pin_name)
            digital_val = pin.analog_to_digital(voltages, prev_value=prev_val)

            # Force onto Verilog signal
            try:
                handle = self._resolve_signal(block.name, pin_name)
                handle.value = Force(digital_val)
            except AttributeError:
                log.warning(
                    "Cannot force signal %s.%s -- handle not found",
                    block.name, pin_name,
                )

    def _release_outputs(self, block: AnalogBlock) -> None:
        """Release all forced output signals."""
        for pin_name, pin in block.digital_pins.items():
            if pin.direction != "output":
                continue
            try:
                handle = self._resolve_signal(block.name, pin_name)
                handle.value = Release()
            except AttributeError:
                pass

    def _resolve_signal(self, block_name: str, pin_name: str) -> Any:
        """Resolve a cocotb signal handle for a pin on an analog block.

        Supports hierarchical block names (e.g., ``"dut.u_analog"``) by
        traversing each component of the dotted path.

        Raises:
            AttributeError: If the signal cannot be found at the hierarchical
                path or as a fallback on the DUT root.
        """
        try:
            handle = self._dut
            for part in block_name.split("."):
                handle = getattr(handle, part)
            return getattr(handle, pin_name)
        except AttributeError:
            try:
                return getattr(self._dut, pin_name)
            except AttributeError:
                raise AttributeError(
                    f"Cannot find signal '{pin_name}' on block '{block_name}' "
                    f"or on DUT root. Check that the block name matches your "
                    f"Verilog hierarchy and the pin name matches the stub port."
                ) from None
