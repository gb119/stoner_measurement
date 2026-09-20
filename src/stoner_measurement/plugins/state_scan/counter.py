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
    """A simple hardware-free scan axis for testing and examples.

    Use this plugin when you want a scan variable without connecting any real
    hardware. It is useful for testing sequences, trying out plotting or data
    collection logic, and understanding how state-scan plugins behave.

    Each scan set-point is applied immediately, so there is no waiting for
    settling and the plugin is always considered to be at target. Internally
    it simply stores the current numeric value, initialised to ``0.0``.

    The configuration tabs consist mainly of the standard state-scan controls,
    especially the scan-generator settings that define the sequence of values
    to visit. There are no hardware-specific settings for this plugin. The
    Help/About tab uses this docstring to explain the role of the plugin as a
    minimal example scan axis.

    The **Data** tab enables collection, selects sequence outputs and their
    column roles, and controls when accumulated data is cleared or appended.

    Attributes:
        _count (float):
            Current stored counter value representing the present scan state.
        instance_name (str):
            Inherited Python identifier for this instance in the Script tab and
            QtConsole.
        comment (str):
            Inherited optional note displayed beside this step.
        sequence_engine (SequenceEngine | None):
            Inherited owning engine and its live namespace; None while
            detached.
        scan_generator (BaseScanGenerator):
            Inherited generator defining successive sequence points.
        value (float):
            Inherited current sequence control value.
        ix (int):
            Inherited zero-based iteration index.
        meas_flag (bool):
            Inherited flag indicating a measurement point.
        collect_data (bool):
            Inherited switch enabling collection of selected sequence outputs.
        data (TraceData):
            Inherited accumulated table; inspect data.df after collection.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        With an instance named ``counter`` in the sequence, use the
        QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            counter.collect_data = True
            counter.value
            counter.data.df.head()
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
            >>> from qtpy.QtWidgets import QApplication
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
            >>> from qtpy.QtWidgets import QApplication
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
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = CounterPlugin()
            >>> plugin.is_at_target()
            True
        """
        return True
