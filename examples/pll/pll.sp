* Charge-pump PLL — behavioral analog model
* Simplified CP-PLL with VCO, charge pump, and loop filter
*
* Ports: ref_clk fb_clk up down vco_out vdd vss
*
* Digital side provides: ref_clk (reference clock input)
* Digital side reads:    vco_out (VCO output, fed back as fb_clk after divider)
* Digital side drives:   up, down (phase detector outputs)
*                        fb_clk (divided VCO output, fed back from digital)

.subckt pll ref_clk fb_clk up down vco_out vdd vss

* --- Charge Pump ---
* UP current source: sources current when UP is high
g_up vdd cp_out cur='5u * v(up) / v(vdd)'
* DOWN current sink: sinks current when DOWN is high
g_down cp_out vss cur='5u * v(down) / v(vdd)'

* --- Loop Filter (2nd order) ---
* Series R-C from cp_out to ground, plus shunt cap
r_lf cp_out lf1 10k
c_lf1 lf1 vss 100p
c_lf2 cp_out vss 10p

* --- VCO (behavioral) ---
* Center frequency: 100 MHz, gain: 50 MHz/V
* Output is a voltage that toggles between VDD and VSS
* Kvco = 50e6 Hz/V, f0 = 100e6 Hz at Vctrl = Vdd/2
b_vco vco_out vss v='v(vdd) * (sin(6.283185 * (100e6 + 50e6 * (v(cp_out) - v(vdd)/2)) * time) > 0 ? 1 : 0)'

* Small load caps
c_vco vco_out vss 10f

.ends pll
