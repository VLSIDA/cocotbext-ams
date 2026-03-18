"""cocotb test for PWM DAC mixed-signal co-simulation tutorial.

Demonstrates cocotbext-ams with a hardware successive-approximation
controller that binary-searches PWM duty cycles to digitize an
unknown analog input voltage.

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
VIN = 1.15  # analog input voltage to digitize

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
    """Let the hardware SAR controller digitize vin."""

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
        analog_inputs={"vin": VIN},
        vdd=VDD,
        tran_step="0.1n",
        extra_lines=sky130_lines + [
            ".include rc_filter.sp",
            ".include comp.sp",
        ],
    )

    # Simulation: initial settle + N_BITS SAR steps + margin
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

    # --- SAR conversion for vin = 1.15V ---
    target_duty = int(round(VIN / VDD * (2**N_BITS)))
    cocotb.log.info(
        "SAR ADC: digitizing vin=%.2fV  (expect duty≈%d/256)",
        VIN, target_duty,
    )

    # Wait for initial PWM settling before first SAR step
    await Timer(5, "us")

    # Watch each SAR step: the comparator output q decides each bit
    bits = []

    for step in range(N_BITS):
        await RisingEdge(dut.sar_clk)
        await Timer(100, "ns")  # let combinational logic settle

        q_val = int(dut.dut.u_analog.q.value)
        v_filt = bridge.get_analog_voltage("dut.u_analog", "v_filtered")

        # SAR decision: q=1 means DAC > vin → bit is 0 (too high)
        #               q=0 means DAC ≤ vin → bit is 1 (keep it)
        bit = 0 if q_val == 1 else 1
        bits.append(bit)
        partial = "".join(str(b) for b in bits).ljust(N_BITS, ".")

        cocotb.log.info(
            "  bit[%d]: q=%d → %d  |  %s  v_filtered=%.3fV",
            N_BITS - 1 - step, q_val, bit, partial, v_filt,
        )

    # Wait for done
    if not int(dut.done.value):
        await RisingEdge(dut.done)

    result = int(dut.u_sar.duty.value)
    result_voltage = result / (2**N_BITS) * VDD
    binary_str = format(result, f"0{N_BITS}b")
    cocotb.log.info(
        "Result: %s (0x%02X) = %d/256 → %.3fV  (vin=%.3fV)",
        binary_str, result, result, result_voltage, VIN,
    )

    error = abs(result - target_duty)
    assert error <= 2, (
        f"SAR result {result} too far from expected {target_duty} "
        f"(error={error})"
    )

    await bridge.stop()

    cocotb.log.info("View waveforms:")
    cocotb.log.info("  Digital:  tb_pwm_dac.vcd")
    cocotb.log.info("  Analog:   pwm_dac_analog.vcd")
