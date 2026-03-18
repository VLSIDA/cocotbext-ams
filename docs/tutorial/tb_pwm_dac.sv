// Testbench for SAR ADC mixed-signal co-simulation tutorial.
//
// Instantiates the adc module which contains the PWM generator,
// SAR controller, and SPICE analog block.  cocotb drives the clocks
// and reset; the SAR controller does the binary search in hardware.

`timescale 1ns/1ps

module tb_pwm_dac;
    // Clocks and reset (driven by cocotb)
    reg pwm_clk;
    reg comp_clk;
    reg sar_clk;
    reg reset_n;

    // Outputs
    wire [7:0] duty;
    wire       done;
    wire       vref;

    // ADC: PWM generator + SAR controller + analog comparator
    adc #(.N_BITS(8)) dut (
        .pwm_clk(pwm_clk),
        .comp_clk(comp_clk),
        .sar_clk(sar_clk),
        .reset_n(reset_n),
        .vref(vref),
        .duty(duty),
        .done(done)
    );

    initial begin
        pwm_clk  = 0;
        comp_clk = 0;
        sar_clk  = 0;
        reset_n  = 0;
    end

    // Dump digital waveforms
    initial begin
        $dumpfile("tb_pwm_dac.vcd");
        $dumpvars(0, tb_pwm_dac);
    end
endmodule
