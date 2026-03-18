// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026, Matthew Guthaus
// See LICENSE for details.

// Complete SAR ADC module.
//
// A single fast clock (clk) drives the PWM counter and is divided down
// internally to produce the SAR clock.  The comparator is latched once
// per bit by the SAR controller's comp_clk output.
//
// Clock tree (all derived from clk):
//   clk          -> PWM counter (e.g., 1 GHz)
//   clk/SAR_DIV  -> SAR step clock (e.g., /100 = 10 MHz)
//
// The SAR controller waits SETTLE_CYCLES of the SAR clock between bit
// decisions, then pulses comp_clk to trigger the comparator once.

module adc #(
    parameter N_BITS        = 8,
    parameter SAR_DIV       = 100,  // clk divider for SAR clock
    parameter SETTLE_CYCLES = 500   // SAR clock cycles to wait per bit
)(
    input  wire              clk,        // fast clock (drives everything)
    input  wire              reset_n,
    input  wire              vin,        // analog input to measure (stays X in digital)
    output wire [N_BITS-1:0] value,      // current/final digital value
    output wire              done        // SAR conversion complete
);
    wire pwm_out;
    wire q, qb;
    wire comp_clk;

    // --- Clock divider ---

    // SAR clock: clk / SAR_DIV
    reg [$clog2(SAR_DIV)-1:0] sar_div_count;
    reg                       sar_clk;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            sar_div_count <= 0;
            sar_clk       <= 0;
        end else begin
            if (sar_div_count >= SAR_DIV/2 - 1) begin
                sar_div_count <= 0;
                sar_clk       <= ~sar_clk;
            end else begin
                sar_div_count <= sar_div_count + 1;
            end
        end
    end

    // --- Datapath ---

    // Analog block: RC filter + latch comparator (SPICE via cocotbext-ams)
    // comp_clk from SAR controller triggers comparator once per bit
    pwm_dac u_analog (
        .pwm_in(pwm_out),
        .clk(comp_clk),
        .vin(vin),
        .q(q),
        .qb(qb)
    );

    // PWM generator: converts value register to PWM output
    pwm_gen #(.N_BITS(N_BITS)) u_pwm_gen (
        .clk(clk),
        .reset_n(reset_n),
        .duty(value),
        .pwm_out(pwm_out)
    );

    // SAR controller: binary search with settling delay
    sar_controller #(
        .N_BITS(N_BITS),
        .SETTLE_CYCLES(SETTLE_CYCLES)
    ) u_sar (
        .clk(sar_clk),
        .reset_n(reset_n),
        .comp_q(q),
        .value(value),
        .done(done),
        .comp_clk(comp_clk)
    );
endmodule
