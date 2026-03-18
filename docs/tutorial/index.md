# Tutorial: PWM DAC with SAR Controller

This tutorial walks through a complete mixed-signal co-simulation using
cocotbext-ams.  A hardware SAR (successive-approximation) controller
binary-searches PWM duty cycles to find the voltage matching an analog
reference — the binary search runs entirely in Verilog RTL.

![PWM DAC Tutorial Waveforms](images/pwm_dac_waveforms.png)

*Example output: the SAR controller steps through duty cycles (visible as
changing PWM density), the RC filter settles at each step, and the
comparator output guides the next bit decision. After 8 steps, the duty
cycle converges to match vref.*

## What you'll learn

- Wiring a digital PWM to an analog RC filter in SPICE
- Using a sky130 standard-cell latch comparator for analog-to-digital conversion
- Building a SAR controller in Verilog that binary-searches duty cycles
- Configuring `DigitalPin`, `AnalogBlock`, and `MixedSignalBridge`
- Changing analog inputs (`vref`) at runtime for a second conversion
- Exporting mixed real/digital VCD waveforms for viewing

## Prerequisites

- Python >= 3.10
- [cocotb](https://github.com/cocotb/cocotb) >= 2.0
- [Icarus Verilog](https://github.com/steveicarus/iverilog)
- ngspice >= 45, built with `--with-ngshared` (see [README](../../README.md))
- cocotbext-ams installed (`pip install -e path/to/cocotbext-ams`)
- [sky130 PDK](https://github.com/google/skywater-pdk) with `PDK_ROOT` set:

```bash
export PDK_ROOT=/path/to/your/pdk    # e.g. /usr/share/pdk
# verify:
ls $PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice
```

## Architecture

The `adc` module wraps all three components — the binary search runs
entirely in hardware:

```
                          adc module (adc.sv)
  ┌──────────────────────────────────────────────────────────┐
  │                                                          │
  │   SAR Controller          PWM Generator                  │
  │   (sar_controller.sv)     (pwm_gen.sv)                   │
  │                                                          │
  │   sar_clk ──> clk         pwm_clk ──> clk               │
  │   comp_q <─── q ────┐     duty <────── duty[7:0]        │
  │   duty ──────────────┼──>  pwm_out ─────────┐            │
  │   done               │                      │            │
  │                      │                      v            │
  │                      │    Analog Block (SPICE)           │
  │                      │    (pwm_dac_stub.sv → ngspice)    │
  │                      │    ┌────────────────────────┐     │
  │                      └────┤ q          pwm_in <────┼─────┘
  │                           │ qb                     │     │
  │              comp_clk ───>│ clk                    │     │
  │              vref ───────>│ vref    RC Filter      │     │
  │              (analog)     │         10k + 100pF    │     │
  │                           │         Latch Comp     │     │
  │                           │         (sky130)       │     │
  │                           └────────────────────────┘     │
  └──────────────────────────────────────────────────────────┘
```

**Digital logic (Verilog):** The SAR controller and PWM generator are
synthesizable RTL.  The SAR controller tests one bit per clock edge
(MSB first), using the comparator output to decide whether to keep or
clear each bit.

**Analog (SPICE):** The RC filter smooths the PWM into a DC voltage,
and the sky130 latch comparator compares it against `vref`.

**Bridge:** cocotbext-ams connects them — `ValueChange` monitors
propagate `pwm_out` and `comp_clk` changes to SPICE instantly, and
threshold-crossing detection forces the comparator output `q` back
onto Verilog.  The bridge uses a hierarchical block name
(`"dut.u_analog"`) to reach the SPICE stub inside the `adc` wrapper.

## Files

| File | Purpose |
|------|---------|
| [`adc.sv`](adc.sv) | Top-level ADC: SAR + PWM gen + analog comparator |
| [`sar_controller.sv`](sar_controller.sv) | SAR binary search logic |
| [`pwm_gen.sv`](pwm_gen.sv) | PWM generator from duty register |
| [`pwm_dac_stub.sv`](pwm_dac_stub.sv) | Verilog black-box stub for SPICE block |
| [`rc_filter.sp`](rc_filter.sp) | RC low-pass filter subcircuit |
| [`comp.sp`](comp.sp) | Latch comparator subcircuit (sky130 cells) |
| [`pwm_dac.sp`](pwm_dac.sp) | Top-level SPICE wiring: filter → comparator |
| [`tb_pwm_dac.sv`](tb_pwm_dac.sv) | Testbench instantiating the ADC |
| [`test_pwm_dac.py`](test_pwm_dac.py) | cocotb test (drives clocks, checks result) |
| [`Makefile`](Makefile) | cocotb build/run |

## Step 1: SPICE subcircuits

### RC filter (`rc_filter.sp`)

```spice
.subckt rc_filter pwm_in vout vdd vss
r_filt pwm_in vout 10k
c_filt vout vss 100p
.ends rc_filter
```

A simple first-order low-pass with τ = 10kΩ × 100pF = 1μs.

### Latch comparator (`comp.sp`)

```spice
.subckt comp vinp vinm clk q qb vdd vss
* Cross-coupled NOR3 + NAND3 pairs using sky130 standard cells
* Latches on rising edge of clk
* Outputs q/qb are rail-to-rail digital
...
.ends comp
```

Uses `sky130_fd_sc_hd__nor3_1`, `sky130_fd_sc_hd__nand3_1`, and
`sky130_fd_sc_hd__inv_1`.  The outputs are standard-cell logic levels,
so digitizing them with a threshold makes perfect sense.

### Top-level (`pwm_dac.sp`)

```spice
.subckt pwm_dac pwm_in clk vref q qb vdd vss
Xrc   pwm_in v_filtered vdd vss rc_filter
Xcomp v_filtered vref clk q qb vdd vss comp
.ends pwm_dac
```

## Step 2: Digital RTL

### PWM generator (`pwm_gen.sv`)

```verilog
module pwm_gen #(parameter N_BITS = 8)(
    input  wire              clk,
    input  wire              reset_n,
    input  wire [N_BITS-1:0] duty,
    output reg               pwm_out
);
    reg [N_BITS-1:0] counter;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            counter <= 0;
            pwm_out <= 0;
        end else begin
            counter <= counter + 1;
            pwm_out <= (counter < duty);
        end
    end
endmodule
```

With N_BITS=8 and a 100 MHz clock, one PWM period = 256 × 10ns = 2.56 μs.
The duty register directly controls the output voltage:
V_filtered ≈ (duty / 256) × VDD.

### SAR controller (`sar_controller.sv`)

```verilog
module sar_controller #(parameter N_BITS = 8)(
    input  wire              clk,       // slow SAR step clock
    input  wire              reset_n,
    input  wire              comp_q,    // 1 = filtered > vref
    output reg [N_BITS-1:0]  duty,      // converging duty cycle register
    output reg               done
);
```

The SAR controller works MSB-first:

1. On reset, sets `duty = 10000000` (MSB tentatively set)
2. Each clock edge: reads `comp_q` to evaluate the current bit
   - If `comp_q = 1` (filtered > vref): duty is too high → clear the bit
   - If `comp_q = 0` (filtered ≤ vref): keep the bit set
3. Sets the next bit tentatively and repeats
4. After 8 steps, asserts `done` with the final duty value

### ADC wrapper (`adc.sv`)

```verilog
module adc #(parameter N_BITS = 8)(
    input  wire              pwm_clk, comp_clk, sar_clk, reset_n,
    input  wire              vref,       // analog-only
    output wire [N_BITS-1:0] duty,
    output wire              done
);
    wire pwm_out, q, qb;

    pwm_dac u_analog (                        // SPICE stub
        .pwm_in(pwm_out), .clk(comp_clk),
        .vref(vref), .q(q), .qb(qb)
    );
    pwm_gen #(.N_BITS(N_BITS)) u_pwm_gen (    // PWM generator
        .clk(pwm_clk), .reset_n(reset_n),
        .duty(duty), .pwm_out(pwm_out)
    );
    sar_controller #(.N_BITS(N_BITS)) u_sar ( // SAR logic
        .clk(sar_clk), .reset_n(reset_n),
        .comp_q(q), .duty(duty), .done(done)
    );
endmodule
```

The `adc` module encapsulates the complete system.  The SPICE stub
(`u_analog`) is inside the wrapper, so the bridge uses a hierarchical
block name `"dut.u_analog"` to reach it.

## Step 3: Verilog testbench

```verilog
module tb_pwm_dac;
    reg pwm_clk, comp_clk, sar_clk, reset_n;
    wire [7:0] duty;
    wire done, vref;

    adc #(.N_BITS(8)) dut (
        .pwm_clk(pwm_clk), .comp_clk(comp_clk),
        .sar_clk(sar_clk), .reset_n(reset_n),
        .vref(vref), .duty(duty), .done(done)
    );
endmodule
```

The testbench just instantiates the `adc` and exposes the clock/reset
signals for cocotb to drive.

## Step 4: cocotb test

The Python test is minimal — the binary search runs in hardware:

```python
# The analog block is inside the adc wrapper — use hierarchical name
pwm_dac = AnalogBlock(
    name="dut.u_analog",   # path to SPICE stub inside adc module
    spice_file="pwm_dac.sp",
    subcircuit="pwm_dac",
    digital_pins={...},
    analog_inputs={"vref": 0.9},
    ...
)

bridge = MixedSignalBridge(dut, [pwm_dac], max_sync_interval_ns=50)
await bridge.start(duration_ns=sim_duration, analog_vcd="pwm_dac_analog.vcd",
                   vcd_nodes=["v_filtered"])

# Start clocks
cocotb.start_soon(Clock(dut.pwm_clk, 10, "ns").start())    # 100 MHz
cocotb.start_soon(Clock(dut.comp_clk, 200, "ns").start())   # 5 MHz
cocotb.start_soon(sar_clock(dut, step_us=7))                 # ~7μs/step

# Release reset and let the SAR run
dut.reset_n.value = 1
# ... wait for done ...
await RisingEdge(dut.done)

result = int(dut.u_sar.duty.value)  # e.g., 128 for vref=0.9V
```

The test monitors each SAR step, logging the duty cycle and filtered
voltage as the controller converges.  After the first conversion, it
changes `vref` to 1.35V, resets the SAR, and verifies convergence to
a new duty cycle (~75%).

## Step 5: Run

```bash
cd docs/tutorial
export PDK_ROOT=/path/to/your/pdk
make
```

## Step 6: View waveforms

Two VCD files are produced:

| File | Contents |
|------|----------|
| `tb_pwm_dac.vcd` | Digital signals: `duty[7:0]`, `done`, `pwm_out`, clocks |
| `pwm_dac_analog.vcd` | Analog voltages (`$var real`) + digitized outputs (`$var wire`) |

Load both in your viewer:

```bash
surfer tb_pwm_dac.vcd pwm_dac_analog.vcd
```

What you'll see:

- **`duty[7:0]`** (digital): the SAR register converging bit by bit
- **`pwm_out`** (digital): PWM density changing as duty updates
- **`v_filtered`** (real): the RC-filtered voltage stepping toward vref
- **`vref`** (real): the reference voltage (0.9V, then 1.35V)
- **`q`** (digital): comparator output guiding each SAR decision
- **`done`** (digital): asserted when conversion completes

![PWM DAC Waveforms](images/pwm_dac_waveforms.png)

## How it works under the hood

1. **SAR sets a bit** in the duty register → PWM generator immediately
   changes its output density → `ValueChange` monitor propagates the
   new `pwm_out` to SPICE instantly.

2. **RC filter integrates** the new PWM at full analog resolution.
   The VCD writer records the smooth `v_filtered` trace stepping up
   or down as each bit is tested.

3. **Comparator latches** on `comp_clk` edges throughout settling.
   When `q` crosses the digital threshold, event-driven sync forces
   the value onto Verilog.

4. **SAR reads `q`** on the next `sar_clk` rising edge (after settling)
   and decides to keep or clear the bit.  The slow `sar_clk` period
   (7 μs) ensures the RC filter has settled before each decision.

5. **After 8 steps**, `done` goes high and `duty` holds the final
   result.  The test resets the SAR, changes `vref`, and runs a
   second conversion.

## Next steps

- Change N_BITS to 10 for higher resolution (needs longer simulation)
- Add `hysteresis=0.1` to the output `DigitalPin` to prevent glitching
- Try different RC values and observe settling behavior
- Look at the [SAR ADC example](../../examples/sar_adc/) for a full data converter
- See the [API reference](../../README.md#api-reference) for all options
