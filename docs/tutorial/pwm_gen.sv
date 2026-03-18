// PWM generator: produces a PWM output from an N-bit duty cycle register.
//
// One PWM period = 2^N clock cycles.
// Output is high when counter < duty, low otherwise.

module pwm_gen #(
    parameter N_BITS = 8
)(
    input  wire              clk,
    input  wire              reset_n,
    input  wire [N_BITS-1:0] duty,
    output reg               pwm_out
);
    reg [N_BITS-1:0] counter;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            counter <= 0;
            pwm_out <= 0;
        end else begin
            counter <= counter + 1;
            pwm_out <= (counter < duty);
        end
    end
endmodule
