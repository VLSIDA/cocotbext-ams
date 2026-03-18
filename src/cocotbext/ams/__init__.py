"""cocotbext-ams: ngspice bridge for cocotb mixed-signal co-simulation."""

__version__ = "0.0.1"

from cocotbext.ams._bridge import AnalogBlock, MixedSignalBridge
from cocotbext.ams._pins import DigitalPin
from cocotbext.ams._vcd import AnalogVcdWriter

__all__ = ["AnalogBlock", "AnalogVcdWriter", "DigitalPin", "MixedSignalBridge"]
