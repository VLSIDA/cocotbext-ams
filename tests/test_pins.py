"""Unit tests for DigitalPin."""

from cocotbext.ams._pins import DigitalPin


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
