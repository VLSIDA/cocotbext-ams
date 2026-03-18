* PWM DAC: RC filter + latch comparator
*
* A digital PWM signal is filtered by an RC low-pass to produce
* a trial voltage (DAC output), which is compared against an
* unknown analog input (vin) by a latch comparator.
*
* Ports: pwm_in clk vin q qb vdd vss
*
* pwm_in : digital PWM input (from Verilog)
* clk    : comparator sample clock (from Verilog)
* vin    : analog input voltage to measure (EXTERNAL, runtime-adjustable)
* q, qb  : comparator digital outputs (to Verilog)

.subckt pwm_dac pwm_in clk vin q qb vdd vss

* RC low-pass filter: converts PWM duty cycle to analog voltage
Xrc pwm_in v_filtered vdd vss rc_filter

* Latch comparator: compares DAC output against input
* vinp=v_filtered (DAC output), vinm=vin (input being measured)
Xcomp v_filtered vin clk q qb vdd vss comp

.ends pwm_dac
