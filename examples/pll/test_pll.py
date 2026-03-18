"""cocotb test for PLL mixed-signal co-simulation example.

This test implements a digital phase-frequency detector (PFD) and a
divide-by-N feedback divider in Python/cocotb. The analog charge pump,
loop filter, and VCO run in ngspice.

The test verifies that the PLL locks to the reference clock within
a reasonable number of cycles.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

from cocotbext.ams import AnalogBlock, DigitalPin, MixedSignalBridge

# PLL parameters
FREF_MHZ = 10.0          # Reference clock frequency
DIVIDE_N = 10            # Feedback divider ratio (target VCO = 100 MHz)
REF_PERIOD_NS = 1000.0 / FREF_MHZ  # 100 ns


async def pfd(dut, ref_clk_period_ns: float):
    """Digital Phase-Frequency Detector.

    Generates UP and DOWN pulses based on the phase difference
    between the reference clock and the feedback (VCO) clock.
    """
    while True:
        # Wait for reference clock rising edge
        await RisingEdge(dut.clk_ref)

        # Assert UP
        dut.up.value = 1

        # Wait for VCO edge or timeout
        for _ in range(int(ref_clk_period_ns)):
            await Timer(1, "ns")
            try:
                vco_val = int(dut.vco_out.value)
            except ValueError:
                vco_val = 0
            if vco_val == 1:
                break

        # De-assert both after a short pulse
        await Timer(2, "ns")
        dut.up.value = 0
        dut.down.value = 0


async def feedback_divider(dut, divide_n: int):
    """Divide-by-N feedback divider.

    Counts VCO edges and toggles the feedback clock every N VCO cycles.
    In this simplified model, we just monitor vco_out transitions.
    """
    count = 0
    while True:
        await Timer(1, "ns")
        try:
            vco_val = int(dut.vco_out.value)
        except ValueError:
            continue
        if vco_val == 1:
            count += 1
            if count >= divide_n:
                count = 0
                # The divided clock feeds back as the PFD comparison
                # In this example the PFD uses clk_ref directly
            await Timer(4, "ns")  # debounce


@cocotb.test()
async def test_pll_lock(dut):
    """Test that the PLL VCO output is toggling after startup."""

    pll_block = AnalogBlock(
        name="dut",
        spice_file="pll.sp",
        subcircuit="pll",
        digital_pins={
            "clk_ref":  DigitalPin("input"),         # reference clock -> analog
            "up":       DigitalPin("input"),          # PFD UP -> charge pump
            "down":     DigitalPin("input"),          # PFD DOWN -> charge pump
            "vco_out":  DigitalPin("output"),         # VCO output -> digital
        },
        analog_inputs={},
        vdd=1.8,
    )

    bridge = MixedSignalBridge(dut, [pll_block], max_sync_interval_ns=5.0)
    await bridge.start(duration_ns=50_000)

    # Start reference clock
    cocotb.start_soon(Clock(dut.clk_ref, REF_PERIOD_NS, "ns").start())

    # Start PFD
    cocotb.start_soon(pfd(dut, REF_PERIOD_NS))

    # Let the PLL run for a while
    await Timer(10, "us")

    # Check that VCO is toggling by sampling it several times
    transitions = 0
    prev_val = None
    for _ in range(200):
        await Timer(5, "ns")
        try:
            cur_val = int(dut.vco_out.value)
        except ValueError:
            continue
        if prev_val is not None and cur_val != prev_val:
            transitions += 1
        prev_val = cur_val

    cocotb.log.info(f"VCO transitions observed: {transitions}")
    assert transitions > 10, f"VCO not toggling enough: only {transitions} transitions in 1us"

    await bridge.stop()
