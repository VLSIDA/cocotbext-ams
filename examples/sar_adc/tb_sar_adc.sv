// Testbench top for SAR ADC mixed-signal co-simulation example.

`timescale 1ns/1ps

module tb_sar_adc;
    reg        clk;
    reg        start_conv;
    wire [9:0] data_out;
    wire       ain;

    sar_adc dut (
        .clk(clk),
        .start_conv(start_conv),
        .data_out(data_out),
        .ain(ain)
    );

    initial begin
        clk = 0;
        start_conv = 0;
    end

    // Dump waveforms
    initial begin
        $dumpfile("tb_sar_adc.vcd");
        $dumpvars(0, tb_sar_adc);
    end
endmodule
