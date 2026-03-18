"""cocotb test for SAR ADC mixed-signal co-simulation example."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from cocotbext.ams import AnalogBlock, DigitalPin, MixedSignalBridge


@cocotb.test()
async def test_sar_adc(dut):
    """Exercise the SAR ADC with a known analog input and verify the digital output."""

    adc = AnalogBlock(
        name="dut",
        spice_file="sar_adc.sp",
        subcircuit="sar_adc",
        digital_pins={
            "clk":        DigitalPin("input"),
            "start_conv": DigitalPin("input"),
            "data_out":   DigitalPin("output", width=10),
        },
        analog_inputs={"ain": 0.9},
        vdd=1.8,
    )

    bridge = MixedSignalBridge(dut, [adc], sync_period_ns=50)
    await bridge.start(duration_ns=100_000)

    # Start clock
    cocotb.start_soon(Clock(dut.clk, 100, "ns").start())
    await Timer(1, "us")

    # Trigger conversion
    dut.start_conv.value = 1
    await RisingEdge(dut.clk)
    dut.start_conv.value = 0

    # Wait for SAR conversion (10 bit cycles + margin)
    for _ in range(12):
        await RisingEdge(dut.clk)

    result = int(dut.data_out.value)
    expected = int(0.9 / 1.8 * 1023)
    cocotb.log.info(f"ADC result: {result}, expected: ~{expected}")
    assert abs(result - expected) < 5, f"ADC result {result} too far from expected {expected}"

    await bridge.stop()
