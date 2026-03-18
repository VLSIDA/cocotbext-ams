"""ctypes wrapper for libngspice shared library."""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# ctypes structure definitions (from sharedspice.h)
# --------------------------------------------------------------------------- #

class NgComplex(ctypes.Structure):
    _fields_ = [
        ("cx_real", ctypes.c_double),
        ("cx_imag", ctypes.c_double),
    ]


class VecValues(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("creal", ctypes.c_double),
        ("cimag", ctypes.c_double),
        ("is_scale", ctypes.c_bool),
        ("is_complex", ctypes.c_bool),
    ]


class VecValuesAll(ctypes.Structure):
    _fields_ = [
        ("veccount", ctypes.c_int),
        ("vecindex", ctypes.c_int),
        ("vecsa", ctypes.POINTER(ctypes.POINTER(VecValues))),
    ]


class VectorInfo(ctypes.Structure):
    _fields_ = [
        ("v_name", ctypes.c_char_p),
        ("v_type", ctypes.c_int),
        ("v_flags", ctypes.c_short),
        ("v_realdata", ctypes.POINTER(ctypes.c_double)),
        ("v_compdata", ctypes.POINTER(NgComplex)),
        ("v_length", ctypes.c_int),
    ]


# --------------------------------------------------------------------------- #
# Callback function types
# --------------------------------------------------------------------------- #

SEND_CHAR = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
)
SEND_STAT = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
)
CONTROLLED_EXIT = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool,
    ctypes.c_int, ctypes.c_void_p,
)
SEND_DATA = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(VecValuesAll), ctypes.c_int,
    ctypes.c_int, ctypes.c_void_p,
)
SEND_INIT_DATA = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p
)
BG_THREAD_RUNNING = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p
)
GET_VSRC_DATA = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.c_double,
    ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p,
)
GET_ISRC_DATA = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.c_double,
    ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p,
)
GET_SYNC_DATA = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_double, ctypes.POINTER(ctypes.c_double),
    ctypes.c_double, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p,
)


def _find_libngspice(hint: str | Path | None = None) -> str:
    """Locate libngspice.so, trying hint path first, then system search."""
    if hint is not None:
        p = Path(hint)
        if p.is_file():
            return str(p)
        if p.is_dir():
            for candidate in sorted(p.glob("libngspice*.so*")):
                return str(candidate)
        raise FileNotFoundError(f"Cannot find libngspice at: {hint}")

    found = ctypes.util.find_library("ngspice")
    if found:
        return found
    raise FileNotFoundError(
        "Cannot find libngspice.so. Install ngspice with --with-ngshared "
        "or pass the library path explicitly."
    )


class NgspiceInterface:
    """Wrapper around libngspice shared library via ctypes.

    This class is the sole owner of the ngspice C library handle.
    It registers all required callbacks and provides a Python-friendly API
    for loading circuits, running simulations, and exchanging data.
    """

    def __init__(self, lib_path: str | Path | None = None) -> None:
        self._lib_path = _find_libngspice(lib_path)
        self._lib = ctypes.CDLL(self._lib_path)

        # Data exchange dictionaries
        self._vsrc_values: dict[str, float] = {}
        self._node_voltages: dict[str, float] = {}

        # Sync state
        self._next_sync_time: float = 0.0
        self._spice_time: float = 0.0
        self._simulation_done = False

        # Callback invoked at each sync point — set by the bridge.
        # Signature: () -> None.  Called from the ngspice thread; expected
        # to be a @resume-decorated function that blocks until cocotb is done.
        self._on_sync_point: Any = None

        # Crossing detection state
        self._crossing_detected: bool = False
        self._prev_digital_values: dict[str, int] = {}
        # Registered by bridge: pin_name -> (node_names, DigitalPin)
        self._output_pin_configs: dict[str, tuple[list[str], Any]] = {}

        # Error tracking
        self._error: Exception | None = None

        # Create and store callback instances (prevent GC)
        self._cb_send_char = SEND_CHAR(self._on_send_char)
        self._cb_send_stat = SEND_STAT(self._on_send_stat)
        self._cb_controlled_exit = CONTROLLED_EXIT(self._on_controlled_exit)
        self._cb_send_data = SEND_DATA(self._on_send_data)
        self._cb_send_init_data = SEND_INIT_DATA(self._on_send_init_data)
        self._cb_bg_thread_running = BG_THREAD_RUNNING(self._on_bg_thread_running)
        self._cb_get_vsrc_data = GET_VSRC_DATA(self._on_get_vsrc_data)
        self._cb_get_isrc_data = GET_ISRC_DATA(self._on_get_isrc_data)
        self._cb_get_sync_data = GET_SYNC_DATA(self._on_get_sync_data)

        self._setup_signatures()

        self._lib.ngSpice_Init(
            self._cb_send_char,
            self._cb_send_stat,
            self._cb_controlled_exit,
            self._cb_send_data,
            self._cb_send_init_data,
            self._cb_bg_thread_running,
            None,
        )

        ident = ctypes.c_int(0)
        self._lib.ngSpice_Init_Sync(
            self._cb_get_vsrc_data,
            self._cb_get_isrc_data,
            self._cb_get_sync_data,
            ctypes.byref(ident),
            None,
        )

    def _setup_signatures(self) -> None:
        """Set up ctypes function signatures for type checking."""
        self._lib.ngSpice_Command.argtypes = [ctypes.c_char_p]
        self._lib.ngSpice_Command.restype = ctypes.c_int

        self._lib.ngSpice_Circ.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
        self._lib.ngSpice_Circ.restype = ctypes.c_int

        self._lib.ngGet_Vec_Info.argtypes = [ctypes.c_char_p]
        self._lib.ngGet_Vec_Info.restype = ctypes.POINTER(VectorInfo)

        self._lib.ngSpice_CurPlot.argtypes = []
        self._lib.ngSpice_CurPlot.restype = ctypes.c_char_p

        self._lib.ngSpice_running.argtypes = []
        self._lib.ngSpice_running.restype = ctypes.c_bool

    # ------------------------------------------------------------------ #
    # Callbacks
    # ------------------------------------------------------------------ #

    def _on_send_char(self, msg: bytes, ident: int, userdata: Any) -> int:
        text = msg.decode("utf-8", errors="replace") if msg else ""
        if text.startswith("stderr"):
            log.warning("ngspice: %s", text[7:].strip())
        else:
            log.debug("ngspice: %s", text.strip())
        return 0

    def _on_send_stat(self, msg: bytes, ident: int, userdata: Any) -> int:
        if msg:
            log.debug("ngspice status: %s", msg.decode("utf-8", errors="replace").strip())
        return 0

    def _on_controlled_exit(
        self, exit_status: int, immediate: bool, quit_exit: bool,
        ident: int, userdata: Any,
    ) -> int:
        if not quit_exit:
            self._error = RuntimeError(f"ngspice error exit (status={exit_status})")
            log.error("ngspice requested exit: status=%d", exit_status)
        else:
            log.debug("ngspice quit (status=%d)", exit_status)
        self._simulation_done = True
        self._ngspice_paused.set()
        return 0

    def _on_send_data(
        self, vdata: Any, count: int, ident: int, userdata: Any,
    ) -> int:
        if not vdata:
            return 0
        vva = vdata.contents
        for i in range(vva.veccount):
            vv = vva.vecsa[i].contents
            raw_name = vv.name.decode("utf-8", errors="replace") if vv.name else ""
            # Store under all useful key forms so lookups are forgiving.
            # ngspice may report names like "tran1.v(d0)" or "v(d0)" or "d0".
            self._node_voltages[raw_name] = vv.creal

            # Strip plot prefix (e.g. "tran1.v(d0)" -> "v(d0)")
            if "." in raw_name:
                short = raw_name.split(".", 1)[1]
                self._node_voltages[short] = vv.creal
            else:
                short = raw_name

            # Strip v() wrapper (e.g. "v(d0)" -> "d0")
            if short.startswith("v(") and short.endswith(")"):
                bare = short[2:-1]
                self._node_voltages[bare] = vv.creal

        # Check for threshold crossings on registered output pins
        self._check_crossings()
        return 0

    def _check_crossings(self) -> None:
        """Check output pins for threshold crossings after voltage update."""
        for pin_name, (node_names, pin) in self._output_pin_configs.items():
            voltages = [self._node_voltages.get(n, 0.0) for n in node_names]
            prev_val = self._prev_digital_values.get(pin_name)
            new_val = pin.analog_to_digital(voltages, prev_value=prev_val)
            if prev_val is not None and new_val != prev_val:
                self._crossing_detected = True
            self._prev_digital_values[pin_name] = new_val

    def _on_send_init_data(self, vdata: Any, ident: int, userdata: Any) -> int:
        return 0

    def _on_bg_thread_running(self, running: bool, ident: int, userdata: Any) -> int:
        log.debug("ngspice bg thread running: %s", running)
        if not running:
            self._simulation_done = True
            self._ngspice_paused.set()
        return 0

    def _on_get_vsrc_data(
        self, p_value: Any, time: float, name: bytes, ident: int, userdata: Any,
    ) -> int:
        src_name = name.decode("utf-8", errors="replace") if name else ""
        # ngspice lowercases source names, so try both original and lowered
        value = self._vsrc_values.get(src_name)
        if value is None:
            value = self._vsrc_values.get(src_name.lower())
        if value is not None:
            p_value[0] = value
            return 0
        log.warning("ngspice requested unknown VSRC: %s", src_name)
        p_value[0] = 0.0
        return 0

    def _on_get_isrc_data(
        self, p_value: Any, time: float, name: bytes, ident: int, userdata: Any,
    ) -> int:
        p_value[0] = 0.0
        return 0

    def _on_get_sync_data(
        self, ckttime: float, p_delta: Any, old_delta: float,
        redostep: int, ident: int, location: int, userdata: Any,
    ) -> int:
        """Synchronization callback — controls ngspice timestep advancement.

        Called by ngspice at each internal timestep. We use this to:
        1. On threshold crossing: immediately sync (event-driven).
        2. At fallback interval: sync to bound time drift.
        3. Otherwise: clamp delta so ngspice doesn't overshoot the next sync point.
        """
        if self._simulation_done:
            return 0

        # Event-driven sync: a threshold crossing was detected in SendData
        if self._crossing_detected:
            self._crossing_detected = False
            self._spice_time = ckttime
            if self._on_sync_point is not None:
                self._on_sync_point()
            return 0

        time_to_sync = self._next_sync_time - ckttime

        if time_to_sync <= 0:
            # Reached fallback sync point — hand control to cocotb.
            self._spice_time = ckttime
            if self._on_sync_point is not None:
                self._on_sync_point()
            return 0

        # Clamp delta so we don't overshoot the next sync point
        if p_delta[0] > time_to_sync:
            p_delta[0] = time_to_sync

        return 0

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def load_circuit(self, lines: list[str]) -> None:
        """Load a SPICE circuit from a list of netlist lines.

        Each line corresponds to one line of a SPICE netlist.
        The list should NOT include a trailing NULL — that is added automatically.
        """
        c_lines = (ctypes.c_char_p * (len(lines) + 1))()
        for i, line in enumerate(lines):
            c_lines[i] = line.encode("utf-8")
        c_lines[len(lines)] = None
        ret = self._lib.ngSpice_Circ(c_lines)
        if ret != 0:
            raise RuntimeError(f"ngSpice_Circ failed with code {ret}")

    def command(self, cmd: str) -> None:
        """Send a command to ngspice for immediate execution."""
        ret = self._lib.ngSpice_Command(cmd.encode("utf-8"))
        if ret != 0:
            raise RuntimeError(f"ngSpice_Command('{cmd}') failed with code {ret}")

    def get_vector(self, name: str) -> float:
        """Get the latest value of a named vector from the current plot."""
        vec_info = self._lib.ngGet_Vec_Info(name.encode("utf-8"))
        if not vec_info:
            raise KeyError(f"Vector '{name}' not found")
        vi = vec_info.contents
        if vi.v_length <= 0:
            raise ValueError(f"Vector '{name}' has no data")
        return vi.v_realdata[vi.v_length - 1]

    def get_node_voltage(self, node: str) -> float:
        """Get a node voltage from the SendData cache."""
        return self._node_voltages.get(node, 0.0)

    def set_vsrc(self, name: str, value: float) -> None:
        """Set the value of an EXTERNAL voltage source."""
        self._vsrc_values[name] = value

    def is_running(self) -> bool:
        """Check if ngspice background thread is still running."""
        return bool(self._lib.ngSpice_running())

    def reset(self) -> None:
        """Reset ngspice state."""
        self._node_voltages.clear()
        self._vsrc_values.clear()
        self._simulation_done = False
        self._error = None

    def halt(self) -> None:
        """Halt a running simulation."""
        self._simulation_done = True
        try:
            self.command("bg_halt")
        except RuntimeError:
            pass
