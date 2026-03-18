# Tutorial: PWM DAC with Latch Comparator

This tutorial walks through a complete mixed-signal co-simulation using
cocotbext-ams.  A digital PWM signal is RC-filtered into an analog voltage
and compared against an adjustable reference by a sky130 latch comparator.

## What you'll learn

- Wiring a digital PWM to an analog RC filter in SPICE
- Using a sky130 standard-cell latch comparator for analog-to-digital conversion
- Configuring `DigitalPin`, `AnalogBlock`, and `MixedSignalBridge`
- Changing analog inputs (`vref`) at runtime
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

## The circuit

```
  pwm_in (digital)                          q, qb (digital)
      |                                       |
      v                                       |
  +-------+     v_filtered      +---------+   |
  |  RC   |-----(analog)------->|  Latch  |---+
  | filter|     10k + 100pF     |  Comp   |
  +-------+                     |  (sky130)|
                                |         |
                   vref ------->| vinm    |
                  (analog,      +---------+
                   adjustable)      ^
                                    |
                                   clk (digital)
```

**Digital → Analog path:** The PWM and comparator clock are Verilog signals.
`ValueChange` monitors update SPICE voltage sources the instant they change —
no sync overhead.

**Analog → Digital path:** The comparator outputs `q` and `qb` are built
from sky130 NOR3/NAND3 gates, so they swing rail-to-rail.  When they cross
the digital threshold, event-driven sync immediately forces the new value
onto the Verilog signals.

## Files

| File | Purpose |
|------|---------|
| [`rc_filter.sp`](rc_filter.sp) | RC low-pass filter subcircuit |
| [`comp.sp`](comp.sp) | Latch comparator subcircuit (sky130 cells) |
| [`pwm_dac.sp`](pwm_dac.sp) | Top-level subcircuit wiring filter → comparator |
| [`pwm_dac_stub.sv`](pwm_dac_stub.sv) | Verilog black-box stub |
| [`tb_pwm_dac.sv`](tb_pwm_dac.sv) | Testbench with `$dumpvars` |
| [`test_pwm_dac.py`](test_pwm_dac.py) | cocotb test |
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
A 75% duty-cycle PWM at 10 MHz settles to ~1.35V (75% of 1.8V).

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

## Step 2: Verilog stub

```verilog
module pwm_dac(
    input  wire pwm_in,
    input  wire clk,
    input  wire vref,     // analog-only, stays X
    output reg  q,        // reg for Force()
    output reg  qb
);
    initial begin q = 1'bx; qb = 1'bx; end
endmodule
```

Outputs are `reg` so the bridge can `Force()` values.  `vref` is
analog-only — it stays `X` in the digital domain and is driven entirely
by the SPICE `EXTERNAL` voltage source.

## Step 3: cocotb test

The key parts of `test_pwm_dac.py`:

### Sky130 PDK include

```python
def _sky130_include() -> list[str]:
    pdk_root = os.environ.get("PDK_ROOT")
    spice_file = os.path.join(
        pdk_root, "sky130A", "libs.ref",
        "sky130_fd_sc_hd", "spice", "sky130_fd_sc_hd.spice"
    )
    return [f".include {spice_file}"]
```

The `extra_lines` field on `AnalogBlock` injects these `.include`
directives into the generated SPICE wrapper netlist.

### Analog block configuration

```python
pwm_dac = AnalogBlock(
    name="dut",
    spice_file="pwm_dac.sp",
    subcircuit="pwm_dac",
    digital_pins={
        "pwm_in": DigitalPin("input",  vdd=1.8, vss=0.0),
        "clk":    DigitalPin("input",  vdd=1.8, vss=0.0),
        "q":      DigitalPin("output", vdd=1.8, vss=0.0),
        "qb":     DigitalPin("output", vdd=1.8, vss=0.0),
    },
    analog_inputs={"vref": 0.9},
    vdd=1.8,
    extra_lines=sky130_lines + [
        ".include rc_filter.sp",
        ".include comp.sp",
    ],
)
```

| Pin | Type | Direction |
|-----|------|-----------|
| `pwm_in` | `DigitalPin("input")` | Verilog → SPICE |
| `clk` | `DigitalPin("input")` | Verilog → SPICE |
| `q`, `qb` | `DigitalPin("output")` | SPICE → Verilog |
| `vref` | `analog_inputs` | External, adjustable at runtime |

### Bridge and simulation

```python
bridge = MixedSignalBridge(dut, [pwm_dac], max_sync_interval_ns=50)

await bridge.start(
    duration_ns=20_000,
    analog_vcd="pwm_dac_analog.vcd",
    vcd_nodes=["v_filtered"],    # also record the RC filter output
)
```

The `vcd_nodes=["v_filtered"]` adds the internal RC filter output to the
analog VCD — even though it's not a pin, you can probe any SPICE node.

### Test sequence

```python
# 75% duty cycle PWM -> filtered voltage ~1.35V > 0.9V ref
cocotb.start_soon(pwm_driver(dut, period_ns=100, duty=0.75, ...))
cocotb.start_soon(comp_clock(dut, period_ns=200, ...))

await Timer(5, "us")           # wait for RC to settle
await RisingEdge(dut.clk)      # comparator latches
assert int(dut.q.value) == 1   # filtered > vref -> q=1

# Raise reference above filtered voltage
bridge.set_analog_input("dut", "vref", 1.5)
# ... wait ...
assert int(dut.q.value) == 0   # filtered < vref -> q=0
```

## Step 4: Run

```bash
cd docs/tutorial
export PDK_ROOT=/path/to/your/pdk
make
```

## Step 5: View waveforms

Two VCD files are produced:

| File | Contents |
|------|----------|
| `tb_pwm_dac.vcd` | Digital signals from Icarus Verilog (`wire`/`reg`) |
| `pwm_dac_analog.vcd` | Analog voltages (`$var real`) + digitized outputs (`$var wire`) |

Load both in your viewer:

```bash
surfer tb_pwm_dac.vcd pwm_dac_analog.vcd
```

What you'll see:

- **`pwm_in`** (digital): the fast-switching PWM waveform
- **`v_filtered`** (real): the smooth RC-filtered analog voltage settling to ~1.35V
- **`vref`** (real): the reference voltage, jumping from 0.9V to 1.5V mid-test
- **`q`** (digital, from analog VCD): the comparator output flipping 1→0 when vref is raised
- **`clk`** (digital): the comparator sample clock

The analog VCD shows the exact moment `v_filtered` and `vref` cross,
and the digital VCD shows `q` responding on the next clock edge.

## How it works under the hood

1. **PWM changes** in Verilog → `ValueChange` monitor instantly writes
   the new voltage (0V or 1.8V) to the SPICE `EXTERNAL` source.
   ngspice picks it up on its next internal evaluation step.

2. **RC filter integrates** the PWM in SPICE at full analog resolution.
   Every accepted timestep, `SendData` updates `_node_voltages` and the
   VCD writer records the smooth `v_filtered` trace.

3. **Comparator latches** on the rising edge of `clk`.  When `q` crosses
   the digital threshold, `_check_crossings()` sets `_crossing_detected`.

4. **GetSyncData** sees the flag, calls `@resume`, and the bridge forces
   the new `q`/`qb` values onto Verilog and advances digital time by the
   exact elapsed SPICE time.

5. **vref changes** at runtime via `set_analog_input()` — the SPICE
   `EXTERNAL` source updates immediately.

## Next steps

- Try different PWM duty cycles and observe how `v_filtered` changes
- Add `hysteresis=0.1` to the output `DigitalPin` to prevent glitching
- Look at the [SAR ADC example](../../examples/sar_adc/) for a full data converter
- See the [API reference](../../README.md#api-reference) for all options
