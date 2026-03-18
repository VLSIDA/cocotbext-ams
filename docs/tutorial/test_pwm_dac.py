"""cocotb test for PWM DAC mixed-signal co-simulation tutorial.

Demonstrates cocotbext-ams with a realistic mixed-signal circuit:
  - A digital PWM signal is RC-filtered into an analog voltage
  - A sky130 latch comparator compares the filtered voltage against
    an external analog reference
  - The comparator output (q/qb) is a rail-to-rail digital signal
    from standard cell gates, naturally suited for digitization

This exercises both data paths:
  - Digital -> Analog: PWM and clk drive SPICE voltage sources
  - Analog -> Digital: comparator q/qb are forced onto Verilog signals
"""

import os

import cocotb
from cocotb.triggers import RisingEdge, Timer

from cocotbext.ams import AnalogBlock, DigitalPin, MixedSignalBridge


def _sky130_include() -> list[str]:
    """Build .include lines for the sky130 standard cell SPICE models.

    Expects PDK_ROOT environment variable to point to the open_pdks
    installation (e.g., /usr/share/pdk).
    """
    pdk_root = os.environ.get("PDK_ROOT")
    if pdk_root is None:
        raise RuntimeError(
            "PDK_ROOT environment variable not set. "
            "Point it to your open_pdks installation, e.g.:\n"
            "  export PDK_ROOT=/usr/share/pdk"
        )
    spice_dir = os.path.join(
        pdk_root, "sky130A", "libs.ref", "sky130_fd_sc_hd", "spice"
    )
    spice_file = os.path.join(spice_dir, "sky130_fd_sc_hd.spice")
    if not os.path.isfile(spice_file):
        raise FileNotFoundError(f"sky130 SPICE models not found: {spice_file}")
    return [f".include {spice_file}"]


async def pwm_driver(dut, period_ns: float, duty: float, duration_ns: float):
    """Generate a PWM signal on dut.pwm_in.

    Args:
        period_ns: PWM period in nanoseconds.
        duty: Duty cycle (0.0 to 1.0).
        duration_ns: How long to run.
    """
    on_time = int(period_ns * duty)
    off_time = int(period_ns * (1.0 - duty))
    elapsed = 0.0
    while elapsed < duration_ns:
        dut.pwm_in.value = 1
        await Timer(on_time, "ns")
        dut.pwm_in.value = 0
        await Timer(off_time, "ns")
        elapsed += period_ns


async def comp_clock(dut, period_ns: float, duration_ns: float):
    """Generate a comparator sample clock on dut.clk.

    The comparator latches on the rising edge of clk.
    """
    half = int(period_ns / 2)
    elapsed = 0.0
    while elapsed < duration_ns:
        dut.clk.value = 0
        await Timer(half, "ns")
        dut.clk.value = 1
        await Timer(half, "ns")
        elapsed += period_ns


@cocotb.test()
async def test_pwm_dac(dut):
    """Drive a PWM, filter it, and verify the comparator output."""

    sky130_lines = _sky130_include()

    # Define the analog block
    pwm_dac = AnalogBlock(
        name="dut",
        spice_file="pwm_dac.sp",
        subcircuit="pwm_dac",
        digital_pins={
            "pwm_in": DigitalPin("input", vdd=1.8, vss=0.0),
            "clk":    DigitalPin("input", vdd=1.8, vss=0.0),
            "q":      DigitalPin("output", vdd=1.8, vss=0.0),
            "qb":     DigitalPin("output", vdd=1.8, vss=0.0),
        },
        analog_inputs={"vref": 0.9},  # reference voltage (adjustable)
        vdd=1.8,
        tran_step="0.1n",
        extra_lines=sky130_lines + [
            ".include rc_filter.sp",
            ".include comp.sp",
        ],
    )

    # Create the bridge with event-driven sync
    bridge = MixedSignalBridge(dut, [pwm_dac], max_sync_interval_ns=50)

    sim_duration = 20_000  # 20 us

    # Start co-simulation with analog VCD recording
    # Record the internal filtered voltage alongside the digital signals
    await bridge.start(
        duration_ns=sim_duration,
        analog_vcd="pwm_dac_analog.vcd",
        vcd_nodes=["v_filtered"],
    )

    # --- Test 1: 75% duty cycle -> filtered voltage ~1.35V > 0.9V ref ---
    cocotb.log.info("Test 1: 75%% duty cycle, vref=0.9V — expect q=1")

    # Start PWM (100ns period, 75% duty) and comparator clock (200ns period)
    cocotb.start_soon(pwm_driver(dut, period_ns=100, duty=0.75, duration_ns=sim_duration))
    cocotb.start_soon(comp_clock(dut, period_ns=200, duration_ns=sim_duration))

    # Wait for RC filter to settle (~5 RC time constants = 5us)
    await Timer(5, "us")

    # Sample after a comparator clock rising edge
    await RisingEdge(dut.clk)
    await Timer(10, "ns")  # allow latch to resolve

    q_val = int(dut.q.value)
    v_filt = bridge.get_analog_voltage("dut", "v_filtered")
    cocotb.log.info(f"  Filtered voltage: {v_filt:.3f} V, q={q_val}")
    assert q_val == 1, f"Expected q=1 (filtered > vref), got q={q_val}"

    # --- Test 2: Change vref above the filtered voltage ---
    cocotb.log.info("Test 2: Raise vref to 1.5V — expect q=0")
    bridge.set_analog_input("dut", "vref", 1.5)

    # Wait for a few comparator cycles
    for _ in range(5):
        await RisingEdge(dut.clk)
    await Timer(10, "ns")

    q_val = int(dut.q.value)
    cocotb.log.info(f"  Filtered voltage: {v_filt:.3f} V, vref=1.5V, q={q_val}")
    assert q_val == 0, f"Expected q=0 (filtered < vref), got q={q_val}"

    await bridge.stop()

    cocotb.log.info("Done! View waveforms:")
    cocotb.log.info("  Digital:  tb_pwm_dac.vcd")
    cocotb.log.info("  Analog:   pwm_dac_analog.vcd")
