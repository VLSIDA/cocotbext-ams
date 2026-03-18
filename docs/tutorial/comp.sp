* Latch-based comparator using sky130 standard cells
*
* Compares vinp vs vinm on the rising edge of clk.
* Outputs q and qb are rail-to-rail digital from standard cell gates.
*
* Ports: vinp vinm clk q qb vdd vss

.subckt comp vinp vinm clk q qb vdd vss

* clkb = inv(clk)
Xinvclk clk vss vss vdd vdd clkb sky130_fd_sc_hd__inv_1

* Top cross-coupled NOR3 pair (reset phase)
XnorT vinm clkb n_mid vss vss vdd vdd n_top sky130_fd_sc_hd__nor3_1
XnorM vinp clkb n_top vss vss vdd vdd n_mid sky130_fd_sc_hd__nor3_1

* Bottom cross-coupled NAND3 pair (amplify phase)
XnandM vinm clk p_bot_raw vss vss vdd vdd p_mid_raw sky130_fd_sc_hd__nand3_1
XnandB vinp clk p_mid_raw vss vss vdd vdd p_bot_raw sky130_fd_sc_hd__nand3_1

* Invert NAND outputs
XinvM p_mid_raw vss vss vdd vdd p_mid sky130_fd_sc_hd__inv_1
XinvB p_bot_raw vss vss vdd vdd p_bot sky130_fd_sc_hd__inv_1

* Output latch with reset using clkb
XnorQB n_top q  clkb vss vss vdd vdd qb sky130_fd_sc_hd__nor3_1
XnorQ  n_mid qb clkb vss vss vdd vdd q  sky130_fd_sc_hd__nor3_1

.ends comp
