"""MonitorPlugin — abstract base class for passive experimental-state recorders.

Monitor plugins poll hardware at regular intervals and record auxiliary
experimental quantities such as temperature, ambient pressure, elapsed time,
or lock-in phase.  They run independently from trace acquisition and are
managed by an internal :class:`~PyQt6.QtCore.QTimer`.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from stoner_measurement.plugins.base_plugin import BasePlugin, _ABCQObjectMeta


class MonitorPlugin(QObject, BasePlugin, metaclass=_ABCQObjectMeta):
    """Abstract base class for plugins that passively record experimental state.

    A :class:`MonitorPlugin` polls hardware at a configurable interval and
    emits :attr:`data_available` with the latest readings.  Subclasses must
    implement :attr:`name`, :attr:`quantity_names`, :attr:`units`, and
    :meth:`read`.

    The class provides:

    * **Synchronous read** — :meth:`read` returns the latest reading as a
      ``{quantity: value}`` dict.
    * **Autonomous polling** — :meth:`start_monitoring` starts an internal
      :class:`~PyQt6.QtCore.QTimer`; :meth:`stop_monitoring` stops it.
    * **Reading cache** — :attr:`last_reading` returns the most recent
      successful :meth:`read` result without re-querying the hardware.

    Attributes:
        data_available (pyqtSignal[dict]):
            Emitted after each successful :meth:`read` call with the reading
            dictionary as its argument.
        read_error (pyqtSignal[str]):
            Emitted with a descriptive message if :meth:`read` raises an
            exception during polling.
        _last_reading (dict[str, float]):
            Internal cache updated after each successful poll; exposed
            read-only via the :attr:`last_reading` property.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.monitor import MonitorPlugin
        >>> class _DummyMonitor(MonitorPlugin):
        ...     @property
        ...     def name(self): return "DummyMonitor"
        ...     @property
        ...     def quantity_names(self): return ["temperature"]
        ...     @property
        ...     def units(self): return {"temperature": "K"}
        ...     def read(self): return {"temperature": 300.0}
        >>> m = _DummyMonitor()
        >>> m.plugin_type
        'monitor'
        >>> m.monitor_interval
        1000
        >>> m.last_reading
        {}
        >>> m.read()
        {'temperature': 300.0}
    """

    data_available = pyqtSignal(dict)
    read_error = pyqtSignal(str)
    instance_name_changed = pyqtSignal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the Qt object hierarchy and the internal polling timer."""
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._last_reading: dict[str, float] = {}

    def _on_instance_name_changed(self, old_name: str, new_name: str) -> None:
        """Emit :attr:`instance_name_changed` when the instance name changes."""
        self.instance_name_changed.emit(old_name, new_name)

    @property
    def plugin_type(self) -> str:
        """Short tag identifying this plugin as a monitor.

        Returns:
            (str):
                Always ``"monitor"``.
        """
        return "monitor"

    @property
    @abstractmethod
    def quantity_names(self) -> list[str]:
        """Ordered list of quantity identifiers returned by :meth:`read`.

        Returns:
            (list[str]):
                Names matching the keys in the dict returned by :meth:`read`.
        """

    @property
    @abstractmethod
    def units(self) -> dict[str, str]:
        """Mapping of quantity name to physical unit string.

        Returns:
            (dict[str, str]):
                E.g. ``{"temperature": "K", "pressure": "Pa"}``.
        """

    @abstractmethod
    def read(self) -> dict[str, float]:
        """Perform a single synchronous hardware read and return the results.

        Returns:
            (dict[str, float]):
                Mapping of quantity name to measured value.

        Raises:
            Exception:
                Any hardware communication error; callers should handle
                exceptions appropriately.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor import MonitorPlugin
            >>> class _ConstMonitor(MonitorPlugin):
            ...     @property
            ...     def name(self): return "Const"
            ...     @property
            ...     def quantity_names(self): return ["x"]
            ...     @property
            ...     def units(self): return {"x": "au"}
            ...     def read(self): return {"x": 42.0}
            >>> m = _ConstMonitor()
            >>> m.read()
            {'x': 42.0}
        """

    @property
    def monitor_interval(self) -> int:
        """Polling period in milliseconds used by :meth:`start_monitoring`.

        Returns:
            (int):
                Interval in milliseconds; default ``1000``.
        """
        return 1000

    def start_monitoring(self, interval_ms: int | None = None) -> None:
        """Start the internal polling timer.

        Calls :meth:`read` every *interval_ms* milliseconds (or every
        :attr:`monitor_interval` milliseconds if *interval_ms* is ``None``).
        Results are cached in :attr:`last_reading` and emitted via
        :attr:`data_available`.  Errors from :meth:`read` are emitted via
        :attr:`read_error` rather than propagated.

        Keyword Parameters:
            interval_ms (int | None):
                Override for the polling interval in milliseconds.  If
                ``None``, :attr:`monitor_interval` is used.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor import MonitorPlugin
            >>> class _TM(MonitorPlugin):
            ...     @property
            ...     def name(self): return "TM"
            ...     @property
            ...     def quantity_names(self): return ["v"]
            ...     @property
            ...     def units(self): return {"v": "au"}
            ...     def read(self): return {"v": 1.0}
            >>> m = _TM()
            >>> m.start_monitoring(500)
            >>> m._timer.isActive()
            True
            >>> m.stop_monitoring()
        """
        ms = interval_ms if interval_ms is not None else self.monitor_interval
        self._timer.start(ms)

    def stop_monitoring(self) -> None:
        """Stop the internal polling timer.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor import MonitorPlugin
            >>> class _TM(MonitorPlugin):
            ...     @property
            ...     def name(self): return "TM"
            ...     @property
            ...     def quantity_names(self): return ["v"]
            ...     @property
            ...     def units(self): return {"v": "au"}
            ...     def read(self): return {"v": 1.0}
            >>> m = _TM()
            >>> m.start_monitoring()
            >>> m.stop_monitoring()
            >>> m._timer.isActive()
            False
        """
        self._timer.stop()

    @property
    def last_reading(self) -> dict[str, float]:
        """Cached result of the most recent successful :meth:`read` call.

        Returns an empty dict if :meth:`read` has not been called yet (either
        directly or via the polling timer).

        Returns:
            (dict[str, float]):
                Copy of the most recently cached reading.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor import MonitorPlugin
            >>> class _TM(MonitorPlugin):
            ...     @property
            ...     def name(self): return "TM"
            ...     @property
            ...     def quantity_names(self): return ["v"]
            ...     @property
            ...     def units(self): return {"v": "au"}
            ...     def read(self): return {"v": 7.0}
            >>> m = _TM()
            >>> m.last_reading
            {}
            >>> _ = m.read()
            >>> m._last_reading = {"v": 7.0}
            >>> m.last_reading
            {'v': 7.0}
        """
        return dict(self._last_reading)

    def _poll(self) -> None:
        """Timer callback: call :meth:`read` and emit the appropriate signal."""
        try:
            reading = self.read()
            self._last_reading = reading
            self.data_available.emit(reading)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.read_error.emit(str(exc))

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return action code lines that call :meth:`read` and print the result.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Ignored for :class:`MonitorPlugin` (leaf node).
            render_sub_step (Callable):
                Ignored for :class:`MonitorPlugin`.

        Returns:
            (list[str]):
                Lines calling ``read()`` and printing the reading dict.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor import MonitorPlugin
            >>> class _M(MonitorPlugin):
            ...     @property
            ...     def name(self): return "M"
            ...     @property
            ...     def quantity_names(self): return ["v"]
            ...     @property
            ...     def units(self): return {"v": "au"}
            ...     def read(self): return {"v": 0.0}
            >>> m = _M()
            >>> lines = m.generate_action_code(1, [], lambda s, i: [])
            >>> "    data = m.read()" in lines
            True
        """
        prefix = "    " * indent
        var_name = self.instance_name
        return [
            f"{prefix}data = {var_name}.read()",
            f"{prefix}print(data)",
            "",
        ]

    def reported_values(self) -> dict[str, str]:
        """Return a mapping of quantity names to Python expressions for accessing monitor readings.

        Each entry corresponds to one quantity polled by this plugin.  The key is
        ``"{instance_name}:{quantity_name}"`` (a human-readable identifier) and the value
        is the Python expression ``"{instance_name}.last_reading['{quantity_name}']"`` that
        retrieves the most recently cached scalar reading for that quantity.

        Returns:
            (dict[str, str]):
                Mapping of ``"{instance_name}:{quantity_name}"`` → expression for each
                name in :attr:`quantity_names`.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor import MonitorPlugin
            >>> class _M(MonitorPlugin):
            ...     @property
            ...     def name(self): return "Temp"
            ...     @property
            ...     def quantity_names(self): return ["temperature", "pressure"]
            ...     @property
            ...     def units(self): return {"temperature": "K", "pressure": "Pa"}
            ...     def read(self): return {"temperature": 300.0, "pressure": 1e5}
            >>> m = _M()
            >>> vals = m.reported_values()
            >>> list(vals.keys())
            ['temp:temperature', 'temp:pressure']
            >>> vals['temp:temperature']
            "temp.last_reading['temperature']"
        """
        var = self.instance_name
        return {f"{var}:{qty}": f"{var}.last_reading['{qty}']" for qty in self.quantity_names}
