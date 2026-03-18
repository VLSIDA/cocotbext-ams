// Verilog black-box stub for the PWM DAC analog block.
//
// - pwm_in, clk: digital inputs (Verilog -> SPICE)
// - q, qb: digital outputs (SPICE -> Verilog), declared as reg for Force()
// - vref: analog-only pin, stays X in digital domain

module pwm_dac(
    input  wire pwm_in,
    input  wire clk,
    input  wire vref,     // analog-only, stays X
    output reg  q,
    output reg  qb
);
    initial begin
        q  = 1'bx;
        qb = 1'bx;
    end
endmodule
