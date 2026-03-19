# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
pip install -e ".[dev]"        # Install for development
pytest tests/ -v               # Run all unit tests
pytest tests/test_pins.py -v   # Run a single test file
pytest tests/ -k "test_hysteresis"  # Run tests matching pattern
mypy src/cocotbext/ams/ --ignore-missing-imports  # Type check
ruff check src/ tests/         # Lint
```

Integration examples (require ngspice + iverilog):
```bash
cd examples/sar_adc && make SIM=icarus
cd examples/pll && make SIM=icarus
```

## Architecture

cocotbext-ams bridges cocotb's digital simulation with an analog SPICE simulator (ngspice or Xyce) via shared library APIs (ctypes). It uses **event-driven synchronization** rather than fixed-interval lock-step.

### Supported Simulators

- **ngspice** (default): Callback-driven via libngspice. `GetSyncData` callback triggers sync points.
- **Xyce**: Explicit-stepping via `xyce_simulateUntil()`. The stepping loop triggers sync points at each interval.

Both run inside a `@bridge` thread and periodically call `_on_sync_point()` (a `@resume` function). The difference is only what triggers that call — ngspice's internal callback vs Xyce's explicit loop.

### Module Dependency Flow

```
_bridge.py (MixedSignalBridge, AnalogBlock)
  ├── _simulator.py (SimulatorInterface — ABC with shared state)
  │     ├── _ngspice.py (NgspiceInterface — ctypes wrapper for libngspice)
  │     └── _xyce.py    (XyceInterface — ctypes wrapper for Xyce C API)
  ├── _pins.py    (DigitalPin — D/A and A/D conversion with hysteresis)
  ├── _netlist.py (generate_netlist — simulator-aware SPICE deck augmentation)
  └── _vcd.py     (AnalogVcdWriter — real+digital VCD output)
```

### Simulator Abstraction (`_simulator.py`)

`SimulatorInterface` ABC holds all shared state (`_vsrc_values`, `_node_voltages`, `_spice_time`, `_next_sync_time`, `_prev_digital_values`, `_output_pin_configs`, `_vcd_writer`, etc.) and implements `_check_crossings()` and `_write_vcd()`. Subclasses implement `load_circuit()`, `run_simulation()`, `get_node_voltage()`, `set_vsrc()`, `halt()`, `reset()`, `is_running()`.

### Two Asymmetric Data Paths

**Digital → Analog:** `ValueChange` monitor coroutines update `_vsrc_values` dict instantly. For ngspice, it reads these via `GetVSRCData` callback. For Xyce, they are pushed via `xyce_updateTimeVoltagePairs()` at each step.

**Analog → Digital:** Voltages are read from the simulator and `_check_crossings()` detects threshold crossings. When a crossing is detected, the sync mechanism forces new digital values onto Verilog and advances digital time.

A fallback `max_sync_interval_ns` (default 100ns) ensures periodic sync even without crossings.

### Thread Model

- The simulator runs a blocking simulation in a `@bridge` thread
- **ngspice:** `GetVSRCData` / `SendData` / `GetSyncData` callbacks fire from the ngspice thread; `GetSyncData` calls `@resume` to sync
- **Xyce:** The explicit stepping loop calls `@resume` at each sync interval
- `_vsrc_values` dict is safe via GIL (cocotb writes, simulator reads)
- `_node_voltages` is only read at sync points when the simulator is paused

### Netlist Augmentation

`_netlist.py` wraps the user's `.subckt` with simulator-specific syntax:

| Feature | ngspice | Xyce |
|---------|---------|------|
| Runtime sources | `v_name node 0 dc 0 external` | `YDAC v_name DAC node 0` |
| Output save | `.save v(node)` | `.PRINT TRAN v(node)` |
| Tran command | `.tran step stop uic` | `.TRAN step stop` |
| Include | `.include path` | `.INCLUDE path` |
| End marker | `.end` | `.END` |

The `simulator=` parameter on `generate_netlist()` dispatches to the right generator.

### Vector Name Normalization

ngspice reports names as `"tran1.v(d0)"`, `"v(d0)"`, or `"d0"`. All forms are stored in `_node_voltages` so lookups work with any variant. Xyce stores both the expression form (`v(d0)`) and bare name (`d0`).

## Testing Conventions

- Unit tests in `tests/` do NOT require ngspice or Xyce — they test pins, netlist generation, and VCD writing in isolation.
- Tests that need `NgspiceInterface` create mock instances via `__new__` and manually set required attributes (`_node_voltages`, `_crossing_detected`, `_prev_digital_values`, `_output_pin_configs`, `_spice_time`). These attributes now come from `SimulatorInterface.__init__()`.
- Xyce netlist generation is tested via `test_generate_xyce_netlist()` without requiring Xyce to be installed.
- Integration tests live in `examples/` and require ngspice + iverilog. Xyce integration testing requires Xyce installed.

## Git Commit Rules

- Never add "Co-Authored-By: Claude" or any Claude attribution to commit messages.
