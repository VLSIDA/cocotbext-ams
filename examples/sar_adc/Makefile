TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(PWD)/sar_adc_stub.sv $(PWD)/tb_sar_adc.sv
TOPLEVEL = tb_sar_adc
MODULE = test_sar_adc

# Use Icarus Verilog by default
SIM ?= icarus

include $(shell cocotb-config --makefiles)/Makefile.sim
