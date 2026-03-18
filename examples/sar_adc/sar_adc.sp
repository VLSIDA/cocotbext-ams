* SAR ADC — 10-bit successive approximation ADC
* Simplified behavioral model for mixed-signal co-simulation demo
*
* Ports: clk start_conv ain d9 d8 d7 d6 d5 d4 d3 d2 d1 d0 vdd vss

.subckt sar_adc clk start_conv ain d9 d8 d7 d6 d5 d4 d3 d2 d1 d0 vdd vss

* Internal DAC reference
r_ref vdd vref 1k
c_ref vref vss 1p

* Comparator (behavioral): compares ain to DAC output
* The DAC output is built from the digital bits via a resistor ladder
* For simplicity, this uses a behavioral voltage source
* In a real design this would be a capacitive DAC

* Binary-weighted DAC using voltage-controlled sources
* Each bit contributes vdd * 2^bit / 1024 when high
e_dac dac_out vss vol='(v(d9)*512 + v(d8)*256 + v(d7)*128 + v(d6)*64 + v(d5)*32 + v(d4)*16 + v(d3)*8 + v(d2)*4 + v(d1)*2 + v(d0)*1) / 1024.0 * v(vdd)'

* Comparator: output high if ain > dac_out
e_comp comp_out vss vol='v(vdd) * (atan((v(ain) - v(dac_out)) * 1000) / 3.14159 + 0.5)'

* SAR logic is handled by the digital side
* The SPICE side just provides the DAC and comparator

* Small load caps on outputs (for realistic behavior)
c_d0 d0 vss 10f
c_d1 d1 vss 10f
c_d2 d2 vss 10f
c_d3 d3 vss 10f
c_d4 d4 vss 10f
c_d5 d5 vss 10f
c_d6 d6 vss 10f
c_d7 d7 vss 10f
c_d8 d8 vss 10f
c_d9 d9 vss 10f

.ends sar_adc
