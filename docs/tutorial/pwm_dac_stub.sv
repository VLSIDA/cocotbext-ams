// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026, Matthew Guthaus
// See LICENSE for details.

// Verilog black-box stub for the PWM DAC analog block.
//
// - pwm_in, clk: digital inputs (Verilog -> SPICE)
// - q, qb: digital outputs (SPICE -> Verilog), declared as reg for Force()
// - vin: analog-only pin, stays X in digital domain

module pwm_dac(
    input  wire pwm_in,
    input  wire clk,
    input  wire vin,      // analog-only, stays X
    output reg  q,
    output reg  qb
);
    initial begin
        q  = 1'bx;
        qb = 1'bx;
    end
endmodule
