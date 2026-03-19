# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, Matthew Guthaus
# See LICENSE for details.

"""SPICE netlist augmentation for mixed-signal co-simulation.

Generates a wrapper netlist that includes the user's subcircuit and adds
EXTERNAL voltage sources for digital inputs, power supplies, and .save
directives for probing analog outputs.
"""

from __future__ import annotations

from pathlib import Path

from cocotbext.ams._pins import DigitalPin


def _bit_node_name(pin_name: str, bit: int, width: int) -> str:
    """Generate a SPICE node name for a specific bit of a pin."""
    if width == 1:
        return pin_name
    return f"{pin_name}_{bit}"


def _vsrc_name(pin_name: str, bit: int, width: int) -> str:
    """Generate a voltage source name for a digital input pin bit."""
    node = _bit_node_name(pin_name, bit, width)
    return f"v_dig_{node}"


def generate_netlist(
    spice_file: str | Path,
    subcircuit: str,
    digital_pins: dict[str, DigitalPin],
    analog_inputs: dict[str, float],
    vdd: float = 1.8,
    vss: float = 0.0,
    tran_step: str = "0.1n",
    tran_stop: str = "100u",
    extra_lines: list[str] | None = None,
    simulator: str = "ngspice",
) -> list[str]:
    """Generate a complete SPICE deck wrapping the user's subcircuit.

    Args:
        spice_file: Path to the user's SPICE netlist containing the subcircuit.
        subcircuit: Name of the subcircuit to instantiate.
        digital_pins: Mapping of pin name -> DigitalPin configuration.
        analog_inputs: Mapping of analog input name -> initial voltage.
        vdd: Supply voltage.
        vss: Ground voltage.
        tran_step: Transient analysis step size.
        tran_stop: Transient analysis stop time.
        extra_lines: Additional SPICE lines to include.
        simulator: Simulator backend — ``"ngspice"`` or ``"xyce"``.

    Returns:
        List of netlist lines.
    """
    if simulator == "ngspice":
        return _generate_netlist_ngspice(
            spice_file, subcircuit, digital_pins, analog_inputs,
            vdd, vss, tran_step, tran_stop, extra_lines,
        )
    elif simulator == "xyce":
        return _generate_netlist_xyce(
            spice_file, subcircuit, digital_pins, analog_inputs,
            vdd, vss, tran_step, tran_stop, extra_lines,
        )
    else:
        raise ValueError(f"Unknown simulator: {simulator!r} (expected 'ngspice' or 'xyce')")


def _validate_spice_file(spice_file: str | Path, subcircuit: str) -> Path:
    """Validate that the SPICE file exists and contains the subcircuit."""
    spice_path = Path(spice_file).resolve()
    if not spice_path.is_file():
        raise FileNotFoundError(
            f"SPICE file not found: {spice_path}\n"
            f"Check that spice_file='{spice_file}' points to an existing file."
        )

    # Verify the file contains the expected subcircuit
    spice_content = spice_path.read_text()
    if f".subckt {subcircuit}" not in spice_content.lower().replace(
        f".subckt {subcircuit.lower()}", f".subckt {subcircuit}"
    ):
        # Case-insensitive check for .subckt definition
        has_subckt = any(
            line.strip().lower().startswith(f".subckt {subcircuit.lower()}")
            for line in spice_content.splitlines()
        )
        if not has_subckt:
            raise ValueError(
                f"Subcircuit '{subcircuit}' not found in {spice_path}. "
                f"Check that the subcircuit name matches a .subckt definition."
            )
    return spice_path


def _generate_netlist_ngspice(
    spice_file: str | Path,
    subcircuit: str,
    digital_pins: dict[str, DigitalPin],
    analog_inputs: dict[str, float],
    vdd: float,
    vss: float,
    tran_step: str,
    tran_stop: str,
    extra_lines: list[str] | None,
) -> list[str]:
    """Generate an ngspice-format netlist with EXTERNAL voltage sources."""
    spice_path = _validate_spice_file(spice_file, subcircuit)

    lines: list[str] = []
    lines.append(f"* cocotbext-ams auto-generated wrapper for {subcircuit}")
    lines.append(f".include {spice_path}")
    lines.append("")

    port_connections: list[str] = []
    save_nodes: list[str] = []

    # EXTERNAL voltage sources for digital input pins
    input_pins = {
        name: pin for name, pin in digital_pins.items()
        if pin.direction == "input"
    }
    if input_pins:
        lines.append("* EXTERNAL voltage sources for digital inputs")
        for pin_name, pin in input_pins.items():
            for bit in range(pin.width):
                node = _bit_node_name(pin_name, bit, pin.width)
                vsrc = _vsrc_name(pin_name, bit, pin.width)
                lines.append(f"{vsrc} {node} 0 dc 0 external")
                port_connections.append(node)

    # Output pins -- nodes to be probed
    output_pins = {
        name: pin for name, pin in digital_pins.items()
        if pin.direction == "output"
    }
    if output_pins:
        lines.append("")
        lines.append("* Output nodes (probed by bridge)")
        for pin_name, pin in output_pins.items():
            for bit in range(pin.width):
                node = _bit_node_name(pin_name, bit, pin.width)
                port_connections.append(node)
                save_nodes.append(f"v({node})")

    # Analog input sources (EXTERNAL so they can be changed at runtime)
    if analog_inputs:
        lines.append("")
        lines.append("* Analog input sources (EXTERNAL — controllable at runtime)")
        for name, voltage in analog_inputs.items():
            lines.append(f"v_{name} {name} 0 dc {voltage} external")
            port_connections.append(name)

    # Power supplies
    lines.append("")
    lines.append("* Power supplies")
    lines.append(f"v_vdd vdd 0 dc {vdd}")
    lines.append(f"v_vss vss 0 dc {vss}")

    # Subcircuit instantiation
    lines.append("")
    lines.append("* Subcircuit instantiation")
    ports_str = " ".join(port_connections + ["vdd", "vss"])
    lines.append(f"x1 {ports_str} {subcircuit}")

    # Save directives
    if save_nodes:
        lines.append("")
        lines.append(f".save {' '.join(save_nodes)}")

    # Transient analysis
    lines.append("")
    lines.append(f".tran {tran_step} {tran_stop} uic")

    if extra_lines:
        lines.append("")
        for line in extra_lines:
            lines.append(line)

    lines.append(".end")
    return lines


def _generate_netlist_xyce(
    spice_file: str | Path,
    subcircuit: str,
    digital_pins: dict[str, DigitalPin],
    analog_inputs: dict[str, float],
    vdd: float,
    vss: float,
    tran_step: str,
    tran_stop: str,
    extra_lines: list[str] | None,
) -> list[str]:
    """Generate a Xyce-format netlist with YDAC devices for runtime sources."""
    spice_path = _validate_spice_file(spice_file, subcircuit)

    lines: list[str] = []
    lines.append(f"* cocotbext-ams auto-generated wrapper for {subcircuit}")
    lines.append(f".INCLUDE {spice_path}")
    lines.append("")

    port_connections: list[str] = []
    print_nodes: list[str] = []

    # YDAC devices for digital input pins (Xyce runtime-controllable sources)
    input_pins = {
        name: pin for name, pin in digital_pins.items()
        if pin.direction == "input"
    }
    if input_pins:
        lines.append("* DAC devices for digital inputs")
        for pin_name, pin in input_pins.items():
            for bit in range(pin.width):
                node = _bit_node_name(pin_name, bit, pin.width)
                vsrc = _vsrc_name(pin_name, bit, pin.width)
                lines.append(f"YDAC {vsrc} DAC {node} 0")
                port_connections.append(node)

    # Output pins -- nodes to be probed
    output_pins = {
        name: pin for name, pin in digital_pins.items()
        if pin.direction == "output"
    }
    if output_pins:
        lines.append("")
        lines.append("* Output nodes (probed by bridge)")
        for pin_name, pin in output_pins.items():
            for bit in range(pin.width):
                node = _bit_node_name(pin_name, bit, pin.width)
                port_connections.append(node)
                print_nodes.append(f"v({node})")

    # YDAC devices for analog input sources
    if analog_inputs:
        lines.append("")
        lines.append("* Analog input sources (DAC — controllable at runtime)")
        for name, voltage in analog_inputs.items():
            lines.append(f"YDAC v_{name} DAC {name} 0")
            port_connections.append(name)

    # Power supplies (standard DC sources — not runtime-controlled)
    lines.append("")
    lines.append("* Power supplies")
    lines.append(f"v_vdd vdd 0 dc {vdd}")
    lines.append(f"v_vss vss 0 dc {vss}")

    # Subcircuit instantiation
    lines.append("")
    lines.append("* Subcircuit instantiation")
    ports_str = " ".join(port_connections + ["vdd", "vss"])
    lines.append(f"x1 {ports_str} {subcircuit}")

    # Print directive for output nodes
    if print_nodes:
        lines.append("")
        lines.append(f".PRINT TRAN {' '.join(print_nodes)}")

    # Transient analysis (Xyce uses .TRAN without uic)
    lines.append("")
    lines.append(f".TRAN {tran_step} {tran_stop}")

    if extra_lines:
        lines.append("")
        for line in extra_lines:
            lines.append(line)

    lines.append(".END")
    return lines


def get_vsrc_names(
    digital_pins: dict[str, DigitalPin],
) -> dict[str, list[str]]:
    """Get the EXTERNAL voltage source names for all digital input pins.

    Returns:
        Mapping of pin_name -> list of VSRC names (one per bit, LSB first).
    """
    result: dict[str, list[str]] = {}
    for pin_name, pin in digital_pins.items():
        if pin.direction == "input":
            result[pin_name] = [
                _vsrc_name(pin_name, bit, pin.width)
                for bit in range(pin.width)
            ]
    return result


def get_output_node_names(
    digital_pins: dict[str, DigitalPin],
) -> dict[str, list[str]]:
    """Get the SPICE node names for all digital output pins.

    Returns:
        Mapping of pin_name -> list of node names (one per bit, LSB first).
    """
    result: dict[str, list[str]] = {}
    for pin_name, pin in digital_pins.items():
        if pin.direction == "output":
            result[pin_name] = [
                _bit_node_name(pin_name, bit, pin.width)
                for bit in range(pin.width)
            ]
    return result
