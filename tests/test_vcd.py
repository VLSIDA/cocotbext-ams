"""Unit tests for AnalogVcdWriter and VCD integration with NgspiceInterface."""

import os
import tempfile

from cocotbext.ams._ngspice import NgspiceInterface
from cocotbext.ams._pins import DigitalPin
from cocotbext.ams._vcd import AnalogVcdWriter


def test_basic_real_output():
    """VCD file contains header and real-valued signal changes."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vcd", delete=False) as f:
        path = f.name

    try:
        w = AnalogVcdWriter(path)
        w.register_signal("vout")
        w.register_signal("vref")
        w.open()
        w.write_header()
        w.write_values(0.0, {"vout": 0.0, "vref": 0.9})
        w.write_values(1e-9, {"vout": 0.45, "vref": 0.9})  # vref unchanged
        w.write_values(2e-9, {"vout": 1.2, "vref": 0.9})
        w.close()

        with open(path) as f:
            content = f.read()

        # Check header
        assert "$timescale 1ps $end" in content
        assert "$var real 64" in content
        assert "vout" in content
        assert "vref" in content
        assert "$enddefinitions $end" in content

        # Check timestamps (0ps, 1000ps, 2000ps)
        assert "#0" in content
        assert "#1000" in content
        assert "#2000" in content

        # Check that real values are written
        assert "r0" in content
        assert "r0.9" in content
        assert "r0.45" in content
        assert "r1.2" in content
    finally:
        os.unlink(path)


def test_digital_signal_single_bit():
    """Single-bit digital signals are written as 0/1 without 'b' prefix."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vcd", delete=False) as f:
        path = f.name

    try:
        w = AnalogVcdWriter(path)
        w.register_digital_signal("dout", width=1)
        w.open()
        w.write_header()
        w.write_values(0.0, digital_values={"dout": 0})
        w.write_values(1e-9, digital_values={"dout": 1})
        w.write_values(2e-9, digital_values={"dout": 0})
        w.close()

        with open(path) as f:
            content = f.read()

        assert "$var wire 1" in content
        assert "dout" in content

        lines = content.splitlines()
        # Find value change lines (after #0, #1000, #2000)
        value_lines = [l for l in lines if l and l[0] in "01"]
        assert len(value_lines) == 3
        # First is 0, then 1, then 0
        vid = None
        for l in lines:
            if "$var wire 1" in l:
                vid = l.split()[3]  # extract VCD id
                break
        assert f"0{vid}" in content
        assert f"1{vid}" in content
    finally:
        os.unlink(path)


def test_digital_signal_multi_bit():
    """Multi-bit digital signals are written with 'b' prefix and binary encoding."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vcd", delete=False) as f:
        path = f.name

    try:
        w = AnalogVcdWriter(path)
        w.register_digital_signal("data_out", width=4)
        w.open()
        w.write_header()
        w.write_values(0.0, digital_values={"data_out": 0})
        w.write_values(1e-9, digital_values={"data_out": 5})   # 0101
        w.write_values(2e-9, digital_values={"data_out": 15})  # 1111
        w.close()

        with open(path) as f:
            content = f.read()

        assert "$var wire 4" in content
        assert "data_out" in content
        assert "b0000" in content
        assert "b0101" in content
        assert "b1111" in content
    finally:
        os.unlink(path)


def test_mixed_real_and_digital():
    """Both real and digital signals appear in the same VCD file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vcd", delete=False) as f:
        path = f.name

    try:
        w = AnalogVcdWriter(path)
        w.register_signal("vout")           # real (analog node voltage)
        w.register_digital_signal("dout")   # digital (digitized output)
        w.open()
        w.write_header()
        # Analog voltage rises, digital stays low
        w.write_values(0.0, {"vout": 0.0}, {"dout": 0})
        w.write_values(0.5e-9, {"vout": 0.5})
        # Analog crosses threshold, digital goes high
        w.write_values(1e-9, {"vout": 1.2}, {"dout": 1})
        w.close()

        with open(path) as f:
            content = f.read()

        # Both var types in header
        assert "$var real 64" in content
        assert "$var wire 1" in content
        assert "vout" in content
        assert "dout" in content

        # Real values
        assert "r0.5" in content
        assert "r1.2" in content

        # Digital transitions
        vid = None
        for line in content.splitlines():
            if "$var wire 1" in line:
                vid = line.split()[3]
                break
        assert f"0{vid}" in content
        assert f"1{vid}" in content
    finally:
        os.unlink(path)


def test_only_changed_values_written():
    """Unchanged signals are not re-emitted."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vcd", delete=False) as f:
        path = f.name

    try:
        w = AnalogVcdWriter(path)
        w.register_signal("vout")
        w.register_signal("vref")
        w.open()
        w.write_header()
        w.write_values(0.0, {"vout": 0.0, "vref": 0.9})
        # vref stays at 0.9 — only vout should appear at t=1ns
        w.write_values(1e-9, {"vout": 0.5, "vref": 0.9})
        w.close()

        with open(path) as f:
            lines = f.readlines()

        # Find lines after #1000
        after_t1 = False
        t1_lines = []
        for line in lines:
            if line.strip() == "#1000":
                after_t1 = True
                continue
            if after_t1:
                t1_lines.append(line.strip())

        # Should have vout change but not vref
        assert len(t1_lines) == 1
        assert t1_lines[0].startswith("r0.5")
    finally:
        os.unlink(path)


def test_no_timestamp_for_no_changes():
    """No timestamp is written when no values changed."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vcd", delete=False) as f:
        path = f.name

    try:
        w = AnalogVcdWriter(path)
        w.register_signal("vout")
        w.open()
        w.write_header()
        w.write_values(0.0, {"vout": 1.0})
        w.write_values(1e-9, {"vout": 1.0})  # same value
        w.write_values(2e-9, {"vout": 1.5})  # changed
        w.close()

        with open(path) as f:
            content = f.read()

        assert "#0" in content
        assert "#1000" not in content  # no change at t=1ns
        assert "#2000" in content
    finally:
        os.unlink(path)


def test_unregistered_signals_ignored():
    """Signals not registered are silently ignored in write_values."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vcd", delete=False) as f:
        path = f.name

    try:
        w = AnalogVcdWriter(path)
        w.register_signal("vout")
        w.open()
        w.write_header()
        w.write_values(0.0, {"vout": 1.0, "unknown_node": 3.3})
        w.close()

        with open(path) as f:
            content = f.read()

        assert "vout" in content
        assert "unknown_node" not in content
    finally:
        os.unlink(path)


def test_make_id_uniqueness():
    """VCD identifiers are unique for at least 200 signals."""
    ids = set()
    for i in range(200):
        vid = AnalogVcdWriter._make_id(i)
        assert vid not in ids, f"Duplicate ID at index {i}: {vid}"
        ids.add(vid)


def test_custom_scope_and_timescale():
    """Custom scope and timescale appear in header."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vcd", delete=False) as f:
        path = f.name

    try:
        w = AnalogVcdWriter(path, timescale="1ns", scope="spice")
        w.register_signal("v1")
        w.open()
        w.write_header()
        w.close()

        with open(path) as f:
            content = f.read()

        assert "$timescale 1ns $end" in content
        assert "$scope module spice $end" in content
    finally:
        os.unlink(path)


# ------------------------------------------------------------------ #
# Integration: VCD writing via NgspiceInterface path
# ------------------------------------------------------------------ #

def _make_ngspice_with_vcd(vcd_path, analog_names, digital_pins=None):
    """Create a mock NgspiceInterface with VCD writer attached."""
    ngspice = NgspiceInterface.__new__(NgspiceInterface)
    ngspice._node_voltages = {}
    ngspice._crossing_detected = False
    ngspice._prev_digital_values = {}
    ngspice._output_pin_configs = {}

    vcd = AnalogVcdWriter(vcd_path)
    for name in analog_names:
        vcd.register_signal(name)
    if digital_pins:
        for name, width in digital_pins:
            vcd.register_digital_signal(name, width)
    vcd.open()
    vcd.write_header()
    ngspice._vcd_writer = vcd
    return ngspice


def test_send_data_writes_real_and_digital():
    """Simulated data sequence produces VCD with real analog + digital outputs."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vcd", delete=False) as f:
        path = f.name

    try:
        pin = DigitalPin("output", vdd=1.8, vss=0.0)
        ngspice = _make_ngspice_with_vcd(
            path,
            analog_names=["out_node", "ain"],
            digital_pins=[("dout", 1)],
        )
        ngspice._output_pin_configs = {"dout": (["out_node"], pin)}

        # Simulate voltage ramp: analog node crosses threshold at 0.9V
        for t, v_out, v_ain in [
            (0.0, 0.0, 0.9),
            (0.5e-9, 0.5, 0.9),
            (1.0e-9, 1.2, 0.9),   # crosses threshold -> dout goes 0->1
            (1.5e-9, 1.8, 0.9),
        ]:
            ngspice._node_voltages["out_node"] = v_out
            ngspice._node_voltages["ain"] = v_ain
            ngspice._check_crossings()
            ngspice._vcd_writer.write_values(
                t,
                analog_values=ngspice._node_voltages,
                digital_values=ngspice._prev_digital_values,
            )

        ngspice._vcd_writer.close()

        with open(path) as f:
            content = f.read()

        # Header has both types
        assert "$var real 64" in content
        assert "$var wire 1" in content
        assert "out_node" in content
        assert "ain" in content
        assert "dout" in content

        # Real voltage values present
        assert "r0.5" in content
        assert "r1.2" in content
        assert "r1.8" in content

        # Digital value: find the wire id and check transitions
        wire_vid = None
        for line in content.splitlines():
            if "$var wire 1" in line and "dout" in line:
                wire_vid = line.split()[3]
                break
        assert wire_vid is not None
        assert f"0{wire_vid}" in content  # initially 0
        assert f"1{wire_vid}" in content  # goes to 1 after crossing
    finally:
        os.unlink(path)


def test_multibit_digital_in_vcd():
    """Multi-bit output pin is recorded as binary in VCD."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vcd", delete=False) as f:
        path = f.name

    try:
        pin = DigitalPin("output", width=4, vdd=1.8, vss=0.0)
        ngspice = _make_ngspice_with_vcd(
            path,
            analog_names=["d_0", "d_1", "d_2", "d_3"],
            digital_pins=[("data_out", 4)],
        )
        ngspice._output_pin_configs = {
            "data_out": (["d_0", "d_1", "d_2", "d_3"], pin),
        }

        # All bits low
        for n in ["d_0", "d_1", "d_2", "d_3"]:
            ngspice._node_voltages[n] = 0.0
        ngspice._check_crossings()
        ngspice._vcd_writer.write_values(
            0.0,
            analog_values=ngspice._node_voltages,
            digital_values=ngspice._prev_digital_values,
        )

        # bits 0 and 2 go high -> value = 5 = 0b0101
        ngspice._node_voltages["d_0"] = 1.8
        ngspice._node_voltages["d_2"] = 1.8
        ngspice._check_crossings()
        ngspice._vcd_writer.write_values(
            1e-9,
            analog_values=ngspice._node_voltages,
            digital_values=ngspice._prev_digital_values,
        )

        ngspice._vcd_writer.close()

        with open(path) as f:
            content = f.read()

        assert "$var wire 4" in content
        assert "b0000" in content  # initial: all low
        assert "b0101" in content  # bits 0,2 high = 5
    finally:
        os.unlink(path)
