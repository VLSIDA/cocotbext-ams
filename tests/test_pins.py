"""Unit tests for DigitalPin and crossing detection."""

from cocotbext.ams._pins import DigitalPin
from cocotbext.ams._ngspice import NgspiceInterface


def test_single_bit_d2a():
    pin = DigitalPin("input", vdd=1.8, vss=0.0)
    assert pin.digital_to_analog(0) == [0.0]
    assert pin.digital_to_analog(1) == [1.8]


def test_multi_bit_d2a():
    pin = DigitalPin("input", width=4, vdd=3.3, vss=0.0)
    # value=5 = 0b0101 -> bits: [1, 0, 1, 0] -> [3.3, 0, 3.3, 0]
    assert pin.digital_to_analog(5) == [3.3, 0.0, 3.3, 0.0]


def test_single_bit_a2d():
    pin = DigitalPin("output", vdd=1.8, vss=0.0)
    assert pin.analog_to_digital([0.0]) == 0
    assert pin.analog_to_digital([1.8]) == 1
    assert pin.analog_to_digital([0.8]) == 0  # below threshold 0.9
    assert pin.analog_to_digital([1.0]) == 1  # above threshold 0.9


def test_multi_bit_a2d():
    pin = DigitalPin("output", width=4, vdd=1.8, vss=0.0)
    # threshold = 0.9
    voltages = [1.8, 0.0, 1.8, 0.0]  # bits [1, 0, 1, 0] = 5
    assert pin.analog_to_digital(voltages) == 5


def test_custom_threshold():
    pin = DigitalPin("output", vdd=3.3, vss=0.0, threshold=1.0)
    assert pin.analog_to_digital([0.5]) == 0
    assert pin.analog_to_digital([1.5]) == 1


def test_default_threshold():
    pin = DigitalPin("output", vdd=2.0, vss=-2.0)
    assert pin._effective_threshold() == 0.0
    assert pin.analog_to_digital([-0.5]) == 0
    assert pin.analog_to_digital([0.5]) == 1


# ------------------------------------------------------------------ #
# Hysteresis tests
# ------------------------------------------------------------------ #

def test_hysteresis_rising():
    """Rising transition requires voltage >= threshold + hysteresis/2."""
    pin = DigitalPin("output", vdd=1.8, vss=0.0, hysteresis=0.2)
    # threshold = 0.9, rising = 1.0, falling = 0.8
    # Previously low (0), voltage at 0.95 is below rising threshold
    assert pin.analog_to_digital([0.95], prev_value=0) == 0
    # Voltage at 1.0 meets rising threshold
    assert pin.analog_to_digital([1.0], prev_value=0) == 1
    # Voltage at 1.1 exceeds rising threshold
    assert pin.analog_to_digital([1.1], prev_value=0) == 1


def test_hysteresis_falling():
    """Falling transition requires voltage < threshold - hysteresis/2."""
    pin = DigitalPin("output", vdd=1.8, vss=0.0, hysteresis=0.2)
    # threshold = 0.9, rising = 1.0, falling = 0.8
    # Previously high (1), voltage at 0.85 is above falling threshold
    assert pin.analog_to_digital([0.85], prev_value=1) == 1
    # Voltage at 0.79 is below falling threshold
    assert pin.analog_to_digital([0.79], prev_value=1) == 0


def test_hysteresis_no_prev_value():
    """Without prev_value, hysteresis has no effect (uses simple threshold)."""
    pin = DigitalPin("output", vdd=1.8, vss=0.0, hysteresis=0.2)
    assert pin.analog_to_digital([0.95]) == 1  # above 0.9 threshold
    assert pin.analog_to_digital([0.85]) == 0  # below 0.9 threshold


def test_hysteresis_zero():
    """Zero hysteresis with prev_value behaves like simple threshold."""
    pin = DigitalPin("output", vdd=1.8, vss=0.0, hysteresis=0.0)
    assert pin.analog_to_digital([0.95], prev_value=0) == 1
    assert pin.analog_to_digital([0.85], prev_value=1) == 0


def test_hysteresis_multibit():
    """Hysteresis applies independently to each bit."""
    pin = DigitalPin("output", width=2, vdd=1.8, vss=0.0, hysteresis=0.2)
    # prev_value=0b01 (bit0=1, bit1=0)
    # bit0 was high: falling threshold = 0.8 -> 0.85 stays high
    # bit1 was low: rising threshold = 1.0 -> 0.95 stays low
    assert pin.analog_to_digital([0.85, 0.95], prev_value=1) == 1
    # bit0 was high: 0.79 < 0.8 -> goes low
    # bit1 was low: 1.1 >= 1.0 -> goes high
    assert pin.analog_to_digital([0.79, 1.1], prev_value=1) == 2


# ------------------------------------------------------------------ #
# Crossing detection tests
# ------------------------------------------------------------------ #

def test_crossing_detection_basic():
    """Crossing detection sets flag when digitized output changes."""
    ngspice = NgspiceInterface.__new__(NgspiceInterface)
    # Initialize only the state we need (skip ctypes/lib init)
    ngspice._node_voltages = {}
    ngspice._crossing_detected = False
    ngspice._prev_digital_values = {}

    pin = DigitalPin("output", vdd=1.8, vss=0.0)
    ngspice._output_pin_configs = {"out": (["out_node"], pin)}

    # First call: no previous value, sets initial but no crossing
    ngspice._node_voltages["out_node"] = 0.0
    ngspice._check_crossings()
    assert not ngspice._crossing_detected
    assert ngspice._prev_digital_values["out"] == 0

    # Voltage rises above threshold -> crossing detected
    ngspice._node_voltages["out_node"] = 1.5
    ngspice._check_crossings()
    assert ngspice._crossing_detected
    assert ngspice._prev_digital_values["out"] == 1

    # Clear and check same value -> no crossing
    ngspice._crossing_detected = False
    ngspice._check_crossings()
    assert not ngspice._crossing_detected


def test_crossing_detection_with_hysteresis():
    """Crossing detection respects hysteresis on output pins."""
    ngspice = NgspiceInterface.__new__(NgspiceInterface)
    ngspice._node_voltages = {}
    ngspice._crossing_detected = False
    ngspice._prev_digital_values = {}

    pin = DigitalPin("output", vdd=1.8, vss=0.0, hysteresis=0.2)
    ngspice._output_pin_configs = {"out": (["out_node"], pin)}

    # Initialize at low
    ngspice._node_voltages["out_node"] = 0.0
    ngspice._check_crossings()
    assert ngspice._prev_digital_values["out"] == 0

    # Voltage at 0.95 — above simple threshold but below rising hysteresis threshold
    ngspice._node_voltages["out_node"] = 0.95
    ngspice._check_crossings()
    assert not ngspice._crossing_detected
    assert ngspice._prev_digital_values["out"] == 0

    # Voltage at 1.1 — above rising threshold (1.0)
    ngspice._node_voltages["out_node"] = 1.1
    ngspice._check_crossings()
    assert ngspice._crossing_detected
    assert ngspice._prev_digital_values["out"] == 1

    # Clear flag, drop to 0.85 — above falling threshold (0.8), stays high
    ngspice._crossing_detected = False
    ngspice._node_voltages["out_node"] = 0.85
    ngspice._check_crossings()
    assert not ngspice._crossing_detected
    assert ngspice._prev_digital_values["out"] == 1

    # Drop to 0.75 — below falling threshold (0.8), crossing detected
    ngspice._node_voltages["out_node"] = 0.75
    ngspice._check_crossings()
    assert ngspice._crossing_detected
    assert ngspice._prev_digital_values["out"] == 0


def test_crossing_detection_multipin():
    """Multiple output pins are checked independently."""
    ngspice = NgspiceInterface.__new__(NgspiceInterface)
    ngspice._node_voltages = {}
    ngspice._crossing_detected = False
    ngspice._prev_digital_values = {}

    pin_a = DigitalPin("output", vdd=1.8, vss=0.0)
    pin_b = DigitalPin("output", vdd=1.8, vss=0.0)
    ngspice._output_pin_configs = {
        "out_a": (["node_a"], pin_a),
        "out_b": (["node_b"], pin_b),
    }

    # Initialize both low
    ngspice._node_voltages["node_a"] = 0.0
    ngspice._node_voltages["node_b"] = 0.0
    ngspice._check_crossings()
    assert not ngspice._crossing_detected

    # Only pin A crosses
    ngspice._node_voltages["node_a"] = 1.5
    ngspice._check_crossings()
    assert ngspice._crossing_detected
    assert ngspice._prev_digital_values["out_a"] == 1
    assert ngspice._prev_digital_values["out_b"] == 0
