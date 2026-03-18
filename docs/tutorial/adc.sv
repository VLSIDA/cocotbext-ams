// Complete SAR ADC module.
//
// Wraps the PWM generator, SAR controller, and analog comparator block
// (SPICE stub) into a single module.  The cocotbext-ams bridge controls
// the internal pwm_dac instance (u_analog) to connect SPICE simulation.

module adc #(
    parameter N_BITS = 8
)(
    input  wire              pwm_clk,    // fast clock for PWM counter
    input  wire              comp_clk,   // comparator latch clock
    input  wire              sar_clk,    // slow clock for SAR steps
    input  wire              reset_n,
    input  wire              vref,       // analog-only (stays X in digital)
    output wire [N_BITS-1:0] duty,       // current/final duty cycle value
    output wire              done        // SAR conversion complete
);
    wire pwm_out;
    wire q, qb;

    // Analog block: RC filter + latch comparator (SPICE via cocotbext-ams)
    pwm_dac u_analog (
        .pwm_in(pwm_out),
        .clk(comp_clk),
        .vref(vref),
        .q(q),
        .qb(qb)
    );

    // PWM generator: converts duty register to PWM output
    pwm_gen #(.N_BITS(N_BITS)) u_pwm_gen (
        .clk(pwm_clk),
        .reset_n(reset_n),
        .duty(duty),
        .pwm_out(pwm_out)
    );

    // SAR controller: binary search for duty cycle matching vref
    sar_controller #(.N_BITS(N_BITS)) u_sar (
        .clk(sar_clk),
        .reset_n(reset_n),
        .comp_q(q),
        .duty(duty),
        .done(done)
    );
endmodule
