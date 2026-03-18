// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026, Matthew Guthaus
// See LICENSE for details.

// Testbench top for PLL mixed-signal co-simulation example.
//
// The testbench instantiates the PLL stub and provides the
// digital PFD and feedback divider logic.

`timescale 1ns/1ps

module tb_pll;
    reg  clk_ref;
    reg  up;
    reg  down;
    wire vco_out;

    pll dut (
        .clk_ref(clk_ref),
        .up(up),
        .down(down),
        .vco_out(vco_out)
    );

    initial begin
        clk_ref = 0;
        up = 0;
        down = 0;
    end

    initial begin
        $dumpfile("tb_pll.vcd");
        $dumpvars(0, tb_pll);
    end
endmodule
