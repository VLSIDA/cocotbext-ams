// Testbench top for PWM DAC mixed-signal co-simulation tutorial.

`timescale 1ns/1ps

module tb_pwm_dac;
    reg  pwm_in;
    reg  clk;
    wire vref;
    wire q;
    wire qb;

    pwm_dac dut (
        .pwm_in(pwm_in),
        .clk(clk),
        .vref(vref),
        .q(q),
        .qb(qb)
    );

    initial begin
        pwm_in = 0;
        clk = 0;
    end

    // Dump digital waveforms
    initial begin
        $dumpfile("tb_pwm_dac.vcd");
        $dumpvars(0, tb_pwm_dac);
    end
endmodule
