"""CounterPlugin — a simple example state-scan plugin that counts through a scan.

The :class:`CounterPlugin` is a minimal, hardware-free implementation of
:class:`~stoner_measurement.plugins.state_scan.StateScanPlugin`.  It maintains
an internal integer counter whose value is set directly to each set-point
supplied by the scan generator.  Because the state transition is instantaneous
there is no settling delay; :meth:`is_at_target` always returns ``True``.

This plugin is intended as a worked example showing how to implement a
:class:`~stoner_measurement.plugins.state_scan.StateScanPlugin` from scratch.
"""

from __future__ import annotations

from stoner_measurement.plugins.state_scan.base import StateScanPlugin


class CounterPlugin(StateScanPlugin):
    """A simple counter that tracks the current scan set-point as its state.

    :class:`CounterPlugin` is a hardware-free example of a
    :class:`~stoner_measurement.plugins.state_scan.StateScanPlugin`.  The
    internal counter is set immediately to whatever value the sequence engine
    passes to :meth:`ramp_to`; no polling or settling time is required.

    The counter is initialised to ``0.0`` at construction.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> plugin = CounterPlugin()
        >>> plugin.name
        'Counter'
        >>> plugin.state_name
        'Value'
        >>> plugin.units
        ''
        >>> plugin.get_state()
        0.0
        >>> plugin.set_state(3.0)
        >>> plugin.get_state()
        3.0
        >>> plugin.is_at_target()
        True
    """

    @property
    def name(self) -> str:
        """Unique identifier for this plugin.

        Returns:
            (str):
                Always ``"Counter"``.
        """
        return "Counter"

    @property
    def state_name(self) -> str:
        """Human-readable name of the controlled quantity.

        Returns:
            (str):
                Always ``"Value"``.
        """
        return "Value"

    @property
    def units(self) -> str:
        """Physical unit of the counter value.

        The counter is dimensionless, so the unit string is empty.

        Returns:
            (str):
                Always ``""`` (empty string).
        """
        return ""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._count: float = 0.0

    def set_state(self, value: float) -> None:
        """Set the internal counter to *value* immediately.

        Args:
            value (float):
                New counter value.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = CounterPlugin()
            >>> plugin.set_state(7.0)
            >>> plugin.get_state()
            7.0
        """
        self._count = float(value)

    def get_state(self) -> float:
        """Return the current counter value.

        Returns:
            (float):
                The value most recently passed to :meth:`set_state`, or
                ``0.0`` before any call to :meth:`set_state`.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = CounterPlugin()
            >>> plugin.get_state()
            0.0
        """
        return self._count

    def is_at_target(self) -> bool:
        """Return ``True`` unconditionally.

        Returns:
            (bool):
                Always ``True``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = CounterPlugin()
            >>> plugin.is_at_target()
            True
        """
        return True
