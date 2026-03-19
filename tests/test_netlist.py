# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, Matthew Guthaus
# See LICENSE for details.

"""Unit tests for netlist generation."""

import tempfile

from cocotbext.ams._netlist import (
    generate_netlist,
    get_output_node_names,
    get_vsrc_names,
)
from cocotbext.ams._pins import DigitalPin


def test_generate_basic_netlist():
    pins = {
        "clk": DigitalPin("input"),
        "data_out": DigitalPin("output", width=4),
    }
    # Create a temporary SPICE file with the expected subcircuit
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sp", delete=False,
    ) as f:
        f.write(".subckt my_block clk data_out_0 data_out_1 data_out_2 data_out_3 ain vdd vss\n")
        f.write("* dummy\n")
        f.write(".ends my_block\n")
        spice_path = f.name

    lines = generate_netlist(
        spice_file=spice_path,
        subcircuit="my_block",
        digital_pins=pins,
        analog_inputs={"ain": 0.9},
        vdd=1.8,
        vss=0.0,
        tran_step="1n",
        tran_stop="10u",
    )
    text = "\n".join(lines)

    # Check EXTERNAL source for input pin
    assert "v_dig_clk clk 0 dc 0 external" in text

    # Check output nodes are probed
    assert "v(data_out_0)" in text
    assert "v(data_out_3)" in text

    # Check analog input source (EXTERNAL for runtime control)
    assert "v_ain ain 0 dc 0.9 external" in text

    # Check power supplies
    assert "v_vdd vdd 0 dc 1.8" in text
    assert "v_vss vss 0 dc 0" in text

    # Check subcircuit instantiation
    assert "my_block" in text

    # Check .tran
    assert ".tran 1n 10u uic" in text

    # Check .end
    assert lines[-1] == ".end"


def test_multi_bit_input_vsrc_names():
    pins = {
        "bus": DigitalPin("input", width=3),
    }
    vsrc = get_vsrc_names(pins)
    assert vsrc == {"bus": ["v_dig_bus_0", "v_dig_bus_1", "v_dig_bus_2"]}


def test_output_node_names():
    pins = {
        "data": DigitalPin("output", width=2),
        "clk": DigitalPin("input"),
    }
    nodes = get_output_node_names(pins)
    assert nodes == {"data": ["data_0", "data_1"]}
    assert "clk" not in nodes


def test_single_bit_names():
    pins = {"clk": DigitalPin("input")}
    vsrc = get_vsrc_names(pins)
    # Single-bit pins don't get _0 suffix
    assert vsrc == {"clk": ["v_dig_clk"]}
