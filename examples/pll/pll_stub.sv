// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026, Matthew Guthaus
// See LICENSE for details.

// Verilog black-box stub for the PLL analog block.
//
// The digital side implements the phase-frequency detector (PFD) and
// the feedback divider. The analog side (ngspice) implements the
// charge pump, loop filter, and VCO.

module pll(
    input  wire clk_ref,     // reference clock from digital
    input  wire up,          // PFD UP signal -> charge pump
    input  wire down,        // PFD DOWN signal -> charge pump
    output reg  vco_out      // VCO output -> digital for feedback
);
    initial vco_out = 0;
endmodule
