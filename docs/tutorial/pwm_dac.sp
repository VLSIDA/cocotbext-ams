* PWM DAC: RC filter + latch comparator
*
* A digital PWM signal is filtered by an RC low-pass to produce
* an analog voltage, which is then compared against an external
* analog reference (vref) by a latch comparator.
*
* Ports: pwm_in clk vref q qb vdd vss
*
* pwm_in : digital PWM input (from Verilog)
* clk    : comparator sample clock (from Verilog)
* vref   : analog reference voltage (EXTERNAL, runtime-adjustable)
* q, qb  : comparator digital outputs (to Verilog)

.subckt pwm_dac pwm_in clk vref q qb vdd vss

* RC low-pass filter: converts PWM to analog level
Xrc pwm_in v_filtered vdd vss rc_filter

* Latch comparator: compares filtered PWM against reference
* vinp=v_filtered, vinm=vref
Xcomp v_filtered vref clk q qb vdd vss comp

.ends pwm_dac
