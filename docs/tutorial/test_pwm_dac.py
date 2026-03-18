# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, Matthew Guthaus
# See LICENSE for details.

"""cocotb test for PWM DAC mixed-signal co-simulation tutorial.

Demonstrates cocotbext-ams with a hardware successive-approximation
controller that binary-searches PWM duty cycles to digitize an
unknown analog input voltage.

Architecture:
  - sar_controller.sv: SAR logic with parameterizable settling delay
  - pwm_gen.sv:        PWM generator (duty register -> PWM output)
  - pwm_dac (SPICE):   RC filter + latch comparator
  - adc.sv:            Wraps everything with internal clock divider

Clock:
  - clk:      1 GHz fast clock for PWM counter
               Divided internally -> 10 MHz SAR clock
               Comparator latched once per bit by SAR controller
               PWM period = 256 ns << RC tau = 10 us (smooth output)

The test just drives clk and waits for the SAR `done` signal.
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

# Timing
# RC filter: tau = 10k * 1nF = 10 us
# PWM clock: 1 GHz (1 ns) -> PWM period = 256 ns << tau (smooth output)
# CLK_DIV = 100 -> SAR clock = 10 MHz (100 ns period)
# SETTLE_CYCLES = 500 SAR clocks = 50 us = 5 tau per bit
CLK_DIV = 100
SAR_CLK_PERIOD_NS = CLK_DIV  # 100 ns at 1 GHz / 100
SETTLE_CYCLES = 500
SETTLE_TIME_NS = SETTLE_CYCLES * SAR_CLK_PERIOD_NS  # 50000 ns = 50 us


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

    # Simulation: initial settle + N_BITS * settle per bit + margin
    sim_duration = int(SETTLE_TIME_NS + N_BITS * SETTLE_TIME_NS + 5000)

    bridge = MixedSignalBridge(dut, [pwm_dac], max_sync_interval_ns=50)

    await bridge.start(
        duration_ns=sim_duration,
        analog_vcd="pwm_dac_analog.vcd",
        vcd_nodes=["v_filtered"],
    )

    # Start fast clock (all other clocks derived internally)
    cocotb.start_soon(Clock(dut.clk, 1, "ns").start())           # 1 GHz

    # Hold reset, then release
    dut.reset_n.value = 0
    await Timer(100, "ns")
    dut.reset_n.value = 1

    # --- SAR conversion for vin ---
    target_value = int(round(VIN / VDD * (2**N_BITS)))
    cocotb.log.info(
        "SAR ADC: digitizing vin=%.2fV  (expect value~%d/256)",
        VIN, target_value,
    )
    cocotb.log.info(
        "  PWM clock: 1 GHz, PWM period: 256 ns, "
        "SAR clock: 10 MHz, settle: %d cycles (%d us)",
        SETTLE_CYCLES, SETTLE_TIME_NS // 1000,
    )

    # Watch each SAR bit decision
    bits = []

    for step in range(N_BITS):
        # Wait for settling + 1 decision cycle
        await Timer(SETTLE_TIME_NS + SAR_CLK_PERIOD_NS, "ns")

        q_val = int(dut.dut.u_analog.q.value)
        v_filt = bridge.get_analog_voltage("dut.u_analog", "v_filtered")

        # SAR decision: q=1 means DAC > vin -> bit is 0 (too high)
        #               q=0 means DAC <= vin -> bit is 1 (keep it)
        bit = 0 if q_val == 1 else 1
        bits.append(bit)
        partial = "".join(str(b) for b in bits).ljust(N_BITS, ".")

        cocotb.log.info(
            "  bit[%d]: q=%d -> %d  |  %s  v_filtered=%.3fV",
            N_BITS - 1 - step, q_val, bit, partial, v_filt,
        )

    # Wait for done
    if not int(dut.done.value):
        await RisingEdge(dut.done)

    result = int(dut.dut.u_sar.value.value)
    result_voltage = result / (2**N_BITS) * VDD
    binary_str = format(result, f"0{N_BITS}b")
    cocotb.log.info(
        "Result: %s (0x%02X) = %d/256 -> %.3fV  (vin=%.3fV)",
        binary_str, result, result, result_voltage, VIN,
    )

    error = abs(result - target_value)
    assert error <= 2, (
        f"SAR result {result} too far from expected {target_value} "
        f"(error={error})"
    )

    await bridge.stop()

    cocotb.log.info("View waveforms:")
    cocotb.log.info("  Digital:  tb_pwm_dac.vcd")
    cocotb.log.info("  Analog:   pwm_dac_analog.vcd")
