// Testbench for SAR ADC mixed-signal co-simulation tutorial.
//
// A single fast clock drives everything.  Internally, the adc module
// divides it down for the SAR clock.  The comparator is latched once
// per bit by the SAR controller.
//
//   clk (1 GHz) -> PWM counter (256 ns period << RC tau = 1 us)
//   clk/100     -> SAR step clock (10 MHz), 50 cycles settle = 5 us/bit

`timescale 1ns/1ps

module tb_pwm_dac;
    // Single clock and reset (driven by cocotb)
    reg clk;
    reg reset_n;

    // Outputs
    wire [7:0] value;
    wire       done;
    wire       vin;

    adc #(
        .N_BITS(8),
        .SAR_DIV(100),
        .SETTLE_CYCLES(50)
    ) dut (
        .clk(clk),
        .reset_n(reset_n),
        .vin(vin),
        .value(value),
        .done(done)
    );

    initial begin
        clk     = 0;
        reset_n = 0;
    end

    // Dump digital waveforms
    initial begin
        $dumpfile("tb_pwm_dac.vcd");
        $dumpvars(0, tb_pwm_dac);
    end
endmodule
