TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(PWD)/pll_stub.sv $(PWD)/tb_pll.sv
TOPLEVEL = tb_pll
MODULE = test_pll

SIM ?= icarus

include $(shell cocotb-config --makefiles)/Makefile.sim
