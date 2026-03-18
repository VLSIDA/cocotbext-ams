// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026, Matthew Guthaus
// See LICENSE for details.

// Successive-approximation controller for PWM DAC.
//
// After setting each trial bit, waits SETTLE_CYCLES of sar_clk for
// the RC filter output to converge, then pulses comp_clk to trigger
// the comparator, and samples comp_q on the next clock edge.
//
// After N_BITS decisions, `done` goes high and `value` holds the result.

module sar_controller #(
    parameter N_BITS        = 8,
    parameter SETTLE_CYCLES = 50   // sar_clk cycles to wait per bit
)(
    input  wire              clk,        // SAR clock
    input  wire              reset_n,
    input  wire              comp_q,     // comparator output (1 = DAC > vin)
    output reg [N_BITS-1:0]  value,      // converging digital value
    output reg               done,
    output reg               comp_clk  // pulses once per bit to trigger comparator
);
    localparam CTR_W = $clog2(SETTLE_CYCLES + 1);

    reg [CTR_W-1:0]        settle_count;
    reg [$clog2(N_BITS):0] bit_idx;

    // States: SETTLE -> LATCH -> DECIDE
    localparam S_SETTLE = 2'd0;
    localparam S_LATCH  = 2'd1;
    localparam S_DECIDE = 2'd2;
    localparam S_DONE   = 2'd3;
    reg [1:0] state;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            value        <= (1 << (N_BITS - 1));
            bit_idx      <= N_BITS - 1;
            done         <= 0;
            comp_clk   <= 0;
            settle_count <= 0;
            state        <= S_SETTLE;
        end else begin
            case (state)
                S_SETTLE: begin
                    comp_clk <= 0;
                    if (settle_count >= SETTLE_CYCLES - 1) begin
                        // Settling done — pulse comparator latch
                        comp_clk   <= 1;
                        settle_count <= 0;
                        state        <= S_LATCH;
                    end else begin
                        settle_count <= settle_count + 1;
                    end
                end

                S_LATCH: begin
                    // comp_clk was high for one cycle; now wait one
                    // cycle for comparator output to propagate
                    comp_clk <= 0;
                    state      <= S_DECIDE;
                end

                S_DECIDE: begin
                    // Sample comparator and decide on current bit
                    if (comp_q) begin
                        // DAC output > vin: value too high, clear this bit
                        value[bit_idx] <= 0;
                    end
                    // else: DAC <= vin, keep this bit set

                    if (bit_idx == 0) begin
                        done  <= 1;
                        state <= S_DONE;
                    end else begin
                        // Set next bit tentatively and wait for settling
                        bit_idx         <= bit_idx - 1;
                        value[bit_idx-1] <= 1;
                        settle_count    <= 0;
                        state           <= S_SETTLE;
                    end
                end

                S_DONE: begin
                    // Stay done
                end
            endcase
        end
    end
endmodule
