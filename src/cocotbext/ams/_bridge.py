"""MixedSignalBridge: time-synchronized co-simulation orchestrator.

Coordinates lock-step simulation between cocotb (digital) and ngspice (analog),
exchanging signals at periodic sync points.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cocotb
from cocotb._bridge import bridge, resume
from cocotb.handle import Force, Release
from cocotb.triggers import Timer

from cocotbext.ams._netlist import (
    generate_netlist,
    get_output_node_names,
    get_vsrc_names,
)
from cocotbext.ams._ngspice import NgspiceInterface
from cocotbext.ams._pins import DigitalPin

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
    """

    name: str
    spice_file: str | Path
    subcircuit: str
    digital_pins: dict[str, DigitalPin] = field(default_factory=dict)
    analog_inputs: dict[str, float] = field(default_factory=dict)
    vdd: float = 1.8
    vss: float = 0.0
    tran_step: str = "0.1n"


class MixedSignalBridge:
    """Orchestrates lock-step co-simulation between cocotb and ngspice.

    The bridge alternates between running ngspice for one sync period
    and advancing the cocotb simulation for one sync period, exchanging
    digital/analog signal values at each sync point.

    Thread model:
        - ngspice runs a blocking ``tran`` command inside a ``@bridge`` thread.
        - At each sync point, the GetSyncData callback blocks the ngspice thread
          and calls back into cocotb via ``@resume`` to exchange signals and
          advance digital time.
        - This avoids polling and the double-thread problem of using ``bg_run``
          inside a ``@bridge`` thread.

    Args:
        dut: cocotb DUT handle.
        analog_blocks: List of AnalogBlock descriptions.
        sync_period_ns: Synchronization interval in nanoseconds.
        ngspice_lib: Path to libngspice.so (auto-detected if None).
    """

    def __init__(
        self,
        dut: Any,
        analog_blocks: list[AnalogBlock],
        sync_period_ns: float = 1.0,
        ngspice_lib: str | Path | None = None,
    ) -> None:
        self._dut = dut
        self._analog_blocks = analog_blocks
        self._sync_period_ns = sync_period_ns
        self._sync_period_sec = sync_period_ns * 1e-9
        self._ngspice_lib = ngspice_lib

        self._ngspice: NgspiceInterface | None = None
        self._running = False

        # Resolved handles and mappings (populated during start)
        self._block_vsrc_names: dict[str, dict[str, list[str]]] = {}
        self._block_output_nodes: dict[str, dict[str, list[str]]] = {}
        self._block_analog_vsrc_names: dict[str, dict[str, str]] = {}

    async def start(self, duration_ns: float) -> None:
        """Start the mixed-signal co-simulation.

        Args:
            duration_ns: Total simulation duration in nanoseconds.
        """
        if self._running:
            raise RuntimeError("Bridge is already running")

        ngspice = NgspiceInterface(self._ngspice_lib)
        self._ngspice = ngspice
        self._running = True

        # Install the sync-point callback that bridges back into cocotb
        ngspice._on_sync_point = self._on_sync_point_resume

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
            )
            ngspice.load_circuit(netlist_lines)

            # Cache VSRC and output node name mappings
            self._block_vsrc_names[block.name] = get_vsrc_names(block.digital_pins)
            self._block_output_nodes[block.name] = get_output_node_names(block.digital_pins)

            # Cache analog input VSRC names (they are also EXTERNAL now)
            self._block_analog_vsrc_names[block.name] = {
                name: f"v_{name}" for name in block.analog_inputs
            }

            # Set initial analog input VSRC values
            for ain_name, voltage in block.analog_inputs.items():
                ngspice.set_vsrc(f"v_{ain_name}", voltage)

            # Set initial digital input VSRC values from Verilog signal states
            self._update_vsrc_from_digital(block)

        # Set initial sync time
        ngspice._next_sync_time = self._sync_period_sec

        log.info(
            "Starting mixed-signal co-simulation: sync_period=%.1fns, duration=%.1fns",
            self._sync_period_ns, duration_ns,
        )

        # Run ngspice blocking tran in a @bridge thread.
        # The GetSyncData callback will call _on_sync_point_resume (a @resume
        # function) at each sync point, which blocks the ngspice thread and
        # runs the signal exchange + Timer advance in the cocotb scheduler.
        tran_step = self._analog_blocks[0].tran_step if self._analog_blocks else "0.1n"
        await self._run_ngspice_tran(tran_step, f"{duration_ns}n")

        self._running = False
        log.info("Mixed-signal co-simulation finished")

    async def stop(self) -> None:
        """Stop the co-simulation and release all forced signals."""
        if not self._running:
            return

        self._running = False

        if self._ngspice is not None:
            self._ngspice.halt()

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
        if self._ngspice is None:
            raise RuntimeError("Bridge not started")

        ain_vsrc = self._block_analog_vsrc_names.get(block_name, {}).get(input_name)
        if ain_vsrc is None:
            raise KeyError(
                f"No analog input '{input_name}' on block '{block_name}'"
            )
        self._ngspice.set_vsrc(ain_vsrc, voltage)

    def get_analog_voltage(self, block_name: str, node: str) -> float:
        """Probe any SPICE node voltage.

        Args:
            block_name: Name of the analog block.
            node: SPICE node name (e.g., "d0", "ain").

        Returns:
            Latest voltage at the node.
        """
        if self._ngspice is None:
            raise RuntimeError("Bridge not started")
        return self._ngspice.get_node_voltage(node)

    # ------------------------------------------------------------------ #
    # Internal: ngspice thread via bridge/resume
    # ------------------------------------------------------------------ #

    @bridge
    def _run_ngspice_tran(self, tran_step: str, tran_stop: str) -> None:
        """Run ngspice blocking tran command in a bridge thread.

        The GetSyncData callback fires at each ngspice timestep. When a sync
        point is reached, it calls the @resume function _on_sync_point_resume,
        which blocks this thread and lets the cocotb scheduler run the signal
        exchange and Timer advance.
        """
        assert self._ngspice is not None
        self._ngspice.command(f"tran {tran_step} {tran_stop} uic")

    @resume
    async def _on_sync_point_resume(self) -> None:
        """Called from the ngspice thread (via GetSyncData) at each sync point.

        This @resume function runs in the cocotb scheduler context:
        1. Reads analog outputs and forces them onto Verilog signals.
        2. Advances digital simulation by one sync period.
        3. Reads Verilog inputs and updates VSRC values for the next ngspice step.
        4. Advances _next_sync_time for the next sync point.
        """
        assert self._ngspice is not None

        if self._ngspice._error is not None:
            raise self._ngspice._error

        # Analog -> Digital: read SPICE outputs, force onto Verilog
        for block in self._analog_blocks:
            self._read_analog_outputs(block)

        # Advance digital simulation
        await Timer(self._sync_period_ns, "ns")

        # Digital -> Analog: read Verilog inputs, update VSRC values
        for block in self._analog_blocks:
            self._update_vsrc_from_digital(block)

        # Advance sync time for the next ngspice interval
        self._ngspice._next_sync_time += self._sync_period_sec

    # ------------------------------------------------------------------ #
    # Internal: signal exchange
    # ------------------------------------------------------------------ #

    def _update_vsrc_from_digital(self, block: AnalogBlock) -> None:
        """Read Verilog input signals and update ngspice VSRC values."""
        assert self._ngspice is not None

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
                self._ngspice.set_vsrc(vsrc_name, voltage)

    def _read_analog_outputs(self, block: AnalogBlock) -> None:
        """Read ngspice output node voltages and force onto Verilog signals."""
        assert self._ngspice is not None

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
                v = self._ngspice.get_node_voltage(node)
                voltages.append(v)

            # Convert to digital value
            digital_val = pin.analog_to_digital(voltages)

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
        """Resolve a cocotb signal handle for a pin on an analog block."""
        try:
            block_handle = getattr(self._dut, block_name)
            return getattr(block_handle, pin_name)
        except AttributeError:
            return getattr(self._dut, pin_name)
