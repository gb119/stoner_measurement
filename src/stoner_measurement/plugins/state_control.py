"""StateControlPlugin — abstract base class for experimental-state controllers.

State-control plugins command hardware to move to a target value and report
when the hardware has settled.  Examples include magnet power-supplies,
temperature controllers, motorised stages, and programmable voltage sources.

A :class:`StateControlPlugin` is the natural "axis" driven by a
:class:`~stoner_measurement.scan.base.BaseScanGenerator`: the generator yields
successive set-point values that are forwarded to :meth:`ramp_to`.
"""

from __future__ import annotations

import math
import time
from abc import abstractmethod

from PyQt6.QtCore import QObject, pyqtSignal

from stoner_measurement.plugins.base_plugin import _ABCQObjectMeta
from stoner_measurement.plugins.sequence_plugin import SequencePlugin


class StateControlPlugin(QObject, SequencePlugin, metaclass=_ABCQObjectMeta):
    """Abstract base class for plugins that control experimental state.

    A :class:`StateControlPlugin` commands an instrument to move to a target
    value and monitors progress until the state has stabilised.  Subclasses
    must implement :attr:`name`, :attr:`state_name`, :attr:`units`,
    :meth:`set_state`, :meth:`get_state`, and :meth:`is_at_target`.

    Inheriting from :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin`
    means that a :class:`StateControlPlugin` item in the sequence tree may act
    as a branch node: other steps can be nested beneath it and will be executed
    via :meth:`execute_sequence` at the appropriate point in the ramp lifecycle.

    The class provides:

    * **Instrument lifecycle** — :meth:`connect`, :meth:`configure`, and
      :meth:`disconnect` form the standard sequence-engine interface for
      opening, configuring, and releasing hardware resources.  Default
      implementations are no-ops; override them in concrete plugins.
    * **Direct control** — :meth:`set_state` and :meth:`get_state` offer
      a low-level read/write interface to the underlying hardware.
    * **Blocking ramp helper** — :meth:`ramp_to` calls :meth:`set_state`,
      then polls :meth:`is_at_target` until settled or a timeout is reached,
      emitting :attr:`state_changed` at each poll and :attr:`state_reached`
      on success.
    * **Safety limits** — :attr:`limits` defines the allowed set-point range;
      :meth:`ramp_to` will emit :attr:`state_error` rather than commanding
      an out-of-range value.
    * **Sub-sequence execution** —
      :meth:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin.execute_sequence`
      connects, configures, runs all sub-step callables in order, then
      disconnects in a ``finally`` block.  Override to add ramp-to logic
      around the sub-steps.

    Attributes:
        state_changed (pyqtSignal[float]):
            Emitted continuously with the current measured value while the
            hardware ramps towards its target.
        state_reached (pyqtSignal[float]):
            Emitted once when the hardware has settled at the target value.
        state_error (pyqtSignal[str]):
            Emitted with a descriptive message if the hardware faults or the
            settle timeout is exceeded.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.state_control import StateControlPlugin
        >>> class _DummyState(StateControlPlugin):
        ...     @property
        ...     def name(self): return "DummyState"
        ...     @property
        ...     def state_name(self): return "Voltage"
        ...     @property
        ...     def units(self): return "V"
        ...     def set_state(self, value): self._v = value
        ...     def get_state(self): return getattr(self, "_v", 0.0)
        ...     def is_at_target(self): return True
        >>> p = _DummyState()
        >>> p.plugin_type
        'state'
        >>> p.limits
        (-inf, inf)
        >>> p.settle_timeout
        60.0
    """

    state_changed = pyqtSignal(float)
    state_reached = pyqtSignal(float)
    state_error = pyqtSignal(str)
    instance_name_changed = pyqtSignal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the Qt object hierarchy."""
        super().__init__(parent)

    def _on_instance_name_changed(self, old_name: str, new_name: str) -> None:
        """Emit :attr:`instance_name_changed` when the instance name changes."""
        self.instance_name_changed.emit(old_name, new_name)

    @property
    def plugin_type(self) -> str:
        """Short tag identifying this plugin as a state controller.

        Returns:
            (str):
                Always ``"state"``.
        """
        return "state"

    # ------------------------------------------------------------------
    # Sub-sequence execution
    # ------------------------------------------------------------------

    def execute_sequence(self, sub_steps: list) -> None:
        """Connect, configure, run *sub_steps* in order, then disconnect.

        This is the default implementation of the
        :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin`
        hook.  It provides a safe lifecycle wrapper:

        1. :meth:`connect` is called to open hardware resources.
        2. :meth:`configure` is called to apply settings.
        3. Each callable in *sub_steps* is invoked in order.
        4. :meth:`disconnect` is called in a ``finally`` block to ensure
           resources are always released even if a sub-step raises.

        Override this method in a concrete subclass to add ramp logic — for
        example, iterating over setpoints from a scan generator and calling
        :meth:`ramp_to` for each one before invoking the sub-step callables.

        Args:
            sub_steps (list):
                Ordered list of zero-argument callables, one per nested step.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _S(StateControlPlugin):
            ...     @property
            ...     def name(self): return "S"
            ...     @property
            ...     def state_name(self): return "X"
            ...     @property
            ...     def units(self): return "au"
            ...     def set_state(self, v): pass
            ...     def get_state(self): return 0.0
            ...     def is_at_target(self): return True
            >>> called = []
            >>> p = _S()
            >>> p.execute_sequence([lambda: called.append(1)])
            >>> called
            [1]
        """
        self.connect()
        self.configure()
        try:
            for sub_step in sub_steps:
                sub_step()
        finally:
            self.disconnect()

    # ------------------------------------------------------------------
    # Instrument lifecycle API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open instrument connections and verify the instrument identity.

        Called once at the start of a measurement sequence to reserve hardware
        resources.  Subclasses should override this method to open serial,
        USB, GPIB, or Ethernet connections and to confirm that the connected
        instrument is the expected type.

        The default implementation is a no-op.  Subclass implementations
        should raise :exc:`RuntimeError` if the instrument cannot be reached
        or is not the expected type.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _S(StateControlPlugin):
            ...     @property
            ...     def name(self): return "S"
            ...     @property
            ...     def state_name(self): return "X"
            ...     @property
            ...     def units(self): return "au"
            ...     def set_state(self, v): pass
            ...     def get_state(self): return 0.0
            ...     def is_at_target(self): return True
            >>> p = _S()
            >>> p.connect()  # no-op by default
        """

    def configure(self) -> None:
        """Apply plugin settings to the instrument.

        Called after :meth:`connect` and before the measurement loop to push
        configuration (output range, ramp rate, etc.) to the hardware.  May
        also be called mid-sequence to reconfigure without reconnecting.

        The default implementation is a no-op.  Override to send the
        appropriate commands to the instrument.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _S(StateControlPlugin):
            ...     @property
            ...     def name(self): return "S"
            ...     @property
            ...     def state_name(self): return "X"
            ...     @property
            ...     def units(self): return "au"
            ...     def set_state(self, v): pass
            ...     def get_state(self): return 0.0
            ...     def is_at_target(self): return True
            >>> p = _S()
            >>> p.configure()  # no-op by default
        """

    def disconnect(self) -> None:
        """Release all reserved instrument resources.

        Called at the end of a measurement sequence (or after an error) to
        cleanly close connections and free hardware resources.  The default
        implementation is a no-op.  Override to close serial/USB/GPIB/Ethernet
        connections.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _S(StateControlPlugin):
            ...     @property
            ...     def name(self): return "S"
            ...     @property
            ...     def state_name(self): return "X"
            ...     @property
            ...     def units(self): return "au"
            ...     def set_state(self, v): pass
            ...     def get_state(self): return 0.0
            ...     def is_at_target(self): return True
            >>> p = _S()
            >>> p.disconnect()  # no-op by default
        """

    @property
    @abstractmethod
    def state_name(self) -> str:
        """Human-readable name of the controlled physical quantity.

        Returns:
            (str):
                E.g. ``"Magnetic Field"``, ``"Temperature"``, ``"Voltage"``.
        """

    @property
    @abstractmethod
    def units(self) -> str:
        """Physical unit of the controlled quantity.

        Returns:
            (str):
                E.g. ``"T"``, ``"K"``, ``"V"``.
        """

    @abstractmethod
    def set_state(self, value: float) -> None:
        """Command the hardware to move towards *value*.

        This method should initiate the change but need not block until the
        hardware has settled; settling is handled by :meth:`ramp_to`.

        Args:
            value (float):
                Target set-point in the units reported by :attr:`units`.
        """

    @abstractmethod
    def get_state(self) -> float:
        """Return the current measured value of the controlled quantity.

        Returns:
            (float):
                Present value in the units reported by :attr:`units`.
        """

    @abstractmethod
    def is_at_target(self) -> bool:
        """Return ``True`` when the hardware has settled at the commanded target.

        Returns:
            (bool):
                ``True`` if the state has stabilised; ``False`` while still
                ramping or settling.
        """

    @property
    def limits(self) -> tuple[float, float]:
        """Allowed set-point range ``(minimum, maximum)``.

        :meth:`ramp_to` rejects targets outside this range by emitting
        :attr:`state_error`.  The default is ``(-inf, inf)`` (no limits).

        Returns:
            (tuple[float, float]):
                ``(min_value, max_value)`` in the units of :attr:`units`.
        """
        return (float("-inf"), float("inf"))

    @property
    def settle_timeout(self) -> float:
        """Maximum time in seconds to wait for the state to reach its target.

        Returns:
            (float):
                Timeout in seconds; default ``60.0``.
        """
        return 60.0

    def ramp_to(self, value: float, poll_interval: float = 0.5) -> None:
        """Command hardware to *value* and block until settled or timed out.

        The method validates *value* against :attr:`limits`, calls
        :meth:`set_state`, then polls :meth:`is_at_target` every
        *poll_interval* seconds.  :attr:`state_changed` is emitted at each
        poll with the current measured value.  :attr:`state_reached` is
        emitted on success; :attr:`state_error` is emitted on timeout or an
        out-of-range target.

        .. note::
            This is a **blocking** call.  In a Qt application, call it from a
            worker thread (e.g. via ``QThreadPool``) to avoid freezing the
            event loop.

        Args:
            value (float):
                Target set-point in the units of :attr:`units`.

        Keyword Parameters:
            poll_interval (float):
                Seconds between successive :meth:`is_at_target` polls;
                default ``0.5``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _InstantState(StateControlPlugin):
            ...     @property
            ...     def name(self): return "Instant"
            ...     @property
            ...     def state_name(self): return "X"
            ...     @property
            ...     def units(self): return "au"
            ...     def set_state(self, v): self._v = v
            ...     def get_state(self): return getattr(self, "_v", 0.0)
            ...     def is_at_target(self): return True
            >>> reached = []
            >>> p = _InstantState()
            >>> p.state_reached.connect(lambda v: reached.append(v))
            >>> p.ramp_to(1.0, poll_interval=0.0)
            >>> reached
            [1.0]
        """
        lo, hi = self.limits
        if (math.isfinite(lo) and value < lo) or (math.isfinite(hi) and value > hi):
            self.state_error.emit(f"Target {value} is outside limits [{lo}, {hi}]")
            return

        self.set_state(value)
        deadline = time.monotonic() + self.settle_timeout
        while not self.is_at_target():
            self.state_changed.emit(self.get_state())
            if time.monotonic() > deadline:
                self.state_error.emit(
                    f"Timeout after {self.settle_timeout}s waiting for state to reach {value}"
                )
                return
            time.sleep(poll_interval)
        self.state_reached.emit(self.get_state())
