// Successive-approximation controller for PWM DAC.
//
// Binary-searches the duty cycle register to find the value that makes
// the filtered PWM voltage match the comparator reference.  Each clock
// edge tests one bit, MSB first.
//
// After N_BITS clock edges, `done` goes high and `duty` holds the result.

module sar_controller #(
    parameter N_BITS = 8
)(
    input  wire              clk,       // SAR step clock (slow — allow RC settling)
    input  wire              reset_n,
    input  wire              comp_q,    // comparator output (1 = filtered > vref)
    output reg [N_BITS-1:0]  duty,      // converging duty cycle register
    output reg               done
);
    reg [$clog2(N_BITS):0] bit_idx;
    reg                    active;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            // Start with MSB set tentatively
            duty   <= (1 << (N_BITS - 1));
            bit_idx <= N_BITS - 1;
            done   <= 0;
            active <= 1;
        end else if (active) begin
            // Evaluate the current bit based on comparator output
            if (comp_q) begin
                // Filtered voltage > vref: duty too high, clear this bit
                duty[bit_idx] <= 0;
            end
            // else: filtered <= vref, keep this bit set

            if (bit_idx == 0) begin
                // All bits resolved
                done   <= 1;
                active <= 0;
            end else begin
                // Set next bit tentatively
                bit_idx        <= bit_idx - 1;
                duty[bit_idx-1] <= 1;
            end
        end
    end
endmodule
