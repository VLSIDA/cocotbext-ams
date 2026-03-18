"""cocotb test for PWM DAC mixed-signal co-simulation tutorial.

Demonstrates cocotbext-ams with a hardware successive-approximation
controller that binary-searches PWM duty cycles to find the voltage
matching a reference.

Architecture:
  - sar_controller.sv: SAR logic (binary search in Verilog)
  - pwm_gen.sv:        PWM generator (duty register → PWM output)
  - pwm_dac (SPICE):   RC filter + latch comparator

The test just drives clocks and waits for the SAR `done` signal.
All the intelligence is in the Verilog SAR controller.
"""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from cocotbext.ams import AnalogBlock, DigitalPin, MixedSignalBridge

# SAR parameters
N_BITS = 8
VDD = 1.8

# Timing: RC filter τ = 10kΩ × 100pF = 1μs, need ~5τ to settle
SAR_STEP_US = 7  # settling + margin per SAR step


def _sky130_include() -> list[str]:
    """Build .include lines for the sky130 standard cell SPICE models."""
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


async def sar_clock(dut, step_us: float):
    """Generate the slow SAR step clock.

    Each period allows the RC filter to settle before the SAR
    controller samples the comparator on the rising edge.
    """
    half = int(step_us * 1000 / 2)  # half-period in ns
    while True:
        dut.sar_clk.value = 0
        await Timer(half, "ns")
        dut.sar_clk.value = 1
        await Timer(half, "ns")


@cocotb.test()
async def test_pwm_dac(dut):
    """Let the hardware SAR controller find the duty cycle matching vref."""

    sky130_lines = _sky130_include()

    # Define the analog block (SPICE RC filter + comparator)
    pwm_dac = AnalogBlock(
        name="dut.u_analog",
        spice_file="pwm_dac.sp",
        subcircuit="pwm_dac",
        digital_pins={
            "pwm_in": DigitalPin("input", vdd=VDD, vss=0.0),
            "clk":    DigitalPin("input", vdd=VDD, vss=0.0),
            "q":      DigitalPin("output", vdd=VDD, vss=0.0),
            "qb":     DigitalPin("output", vdd=VDD, vss=0.0),
        },
        analog_inputs={"vref": 0.9},
        vdd=VDD,
        tran_step="0.1n",
        extra_lines=sky130_lines + [
            ".include rc_filter.sp",
            ".include comp.sp",
        ],
    )

    # Total simulation: initial settle + N_BITS SAR steps + margin
    sim_duration = int((10 + N_BITS * SAR_STEP_US + 10) * 1000)  # in ns

    bridge = MixedSignalBridge(dut, [pwm_dac], max_sync_interval_ns=50)

    await bridge.start(
        duration_ns=sim_duration,
        analog_vcd="pwm_dac_analog.vcd",
        vcd_nodes=["v_filtered"],
    )

    # Start free-running clocks
    # PWM clock: 100 MHz (10ns) → one PWM period = 256 × 10ns = 2.56μs
    cocotb.start_soon(Clock(dut.pwm_clk, 10, "ns").start())
    # Comparator clock: 5 MHz (200ns) — runs continuously
    cocotb.start_soon(Clock(dut.comp_clk, 200, "ns").start())
    # SAR clock: ~7μs period — one binary search step per cycle
    cocotb.start_soon(sar_clock(dut, step_us=SAR_STEP_US))

    # Hold reset for a few PWM cycles, then release
    dut.reset_n.value = 0
    await Timer(1, "us")
    dut.reset_n.value = 1

    # --- SAR conversion for vref = 0.9V ---
    vref = 0.9
    target_duty = int(round(vref / VDD * (2**N_BITS)))
    cocotb.log.info(
        "SAR search: vref=%.2fV, expect duty≈%d/256 (%.1f%%)",
        vref, target_duty, target_duty / 2.56,
    )

    # Wait for initial PWM settling before first SAR step
    await Timer(5, "us")

    # Wait for SAR to finish (N_BITS clock edges + margin)
    for step in range(N_BITS):
        await RisingEdge(dut.sar_clk)
        await Timer(100, "ns")  # let combinational logic settle

        duty_val = int(dut.u_sar.duty.value)
        done_val = int(dut.done.value)
        v_filt = bridge.get_analog_voltage("dut.u_analog", "v_filtered")

        cocotb.log.info(
            "  [%d] duty=%d/256 (%.1f%%)  v_filtered=%.3fV  done=%d",
            step, duty_val, duty_val / 2.56, v_filt, done_val,
        )

    # Wait for done
    if not int(dut.done.value):
        await RisingEdge(dut.done)

    result = int(dut.u_sar.duty.value)
    result_voltage = result / (2**N_BITS) * VDD
    cocotb.log.info(
        "Converged: duty=%d/256 → voltage=%.3fV (target=%.3fV)",
        result, result_voltage, vref,
    )

    error = abs(result - target_duty)
    assert error <= 2, (
        f"SAR result {result} too far from expected {target_duty} "
        f"(error={error})"
    )

    # --- Second conversion: change vref to 1.35V ---
    vref2 = 1.35
    target_duty2 = int(round(vref2 / VDD * (2**N_BITS)))
    bridge.set_analog_input("dut.u_analog", "vref", vref2)
    cocotb.log.info(
        "\nSAR search: vref=%.2fV, expect duty≈%d/256 (%.1f%%)",
        vref2, target_duty2, target_duty2 / 2.56,
    )

    # Reset the SAR controller for a new conversion
    dut.reset_n.value = 0
    await Timer(1, "us")
    dut.reset_n.value = 1
    await Timer(5, "us")

    for step in range(N_BITS):
        await RisingEdge(dut.sar_clk)
        await Timer(100, "ns")

        duty_val = int(dut.u_sar.duty.value)
        done_val = int(dut.done.value)
        v_filt = bridge.get_analog_voltage("dut.u_analog", "v_filtered")

        cocotb.log.info(
            "  [%d] duty=%d/256 (%.1f%%)  v_filtered=%.3fV  done=%d",
            step, duty_val, duty_val / 2.56, v_filt, done_val,
        )

    if not int(dut.done.value):
        await RisingEdge(dut.done)

    result2 = int(dut.u_sar.duty.value)
    result_voltage2 = result2 / (2**N_BITS) * VDD
    cocotb.log.info(
        "Converged: duty=%d/256 → voltage=%.3fV (target=%.3fV)",
        result2, result_voltage2, vref2,
    )

    error2 = abs(result2 - target_duty2)
    assert error2 <= 2, (
        f"SAR result {result2} too far from expected {target_duty2} "
        f"(error={error2})"
    )

    await bridge.stop()

    cocotb.log.info("Done! View waveforms:")
    cocotb.log.info("  Digital:  tb_pwm_dac.vcd")
    cocotb.log.info("  Analog:   pwm_dac_analog.vcd")
