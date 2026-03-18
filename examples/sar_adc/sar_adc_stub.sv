// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026, Matthew Guthaus
// See LICENSE for details.

// Verilog black-box stub for the SAR ADC analog block.
// Output ports are reg so the bridge can Force values onto them.
// The analog-only port (ain) remains X in the digital domain.

module sar_adc(
    input  wire        clk,
    input  wire        start_conv,
    output reg  [9:0]  data_out,
    input  wire        ain          // analog pin - stays X
);
    initial data_out = 10'bx;
endmodule
