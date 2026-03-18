TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(PWD)/pwm_dac_stub.sv $(PWD)/tb_pwm_dac.sv
TOPLEVEL = tb_pwm_dac
MODULE = test_pwm_dac

# Use Icarus Verilog by default
SIM ?= icarus

include $(shell cocotb-config --makefiles)/Makefile.sim
