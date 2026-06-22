"""Temperature controller monitor plugin.

Reads live parameters from the :class:`~stoner_measurement.temperature_control.engine.TemperatureControllerEngine`
and exposes them as output values in the sequence namespace and as attributes of
the plugin instance.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from qtpy.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.plugins.monitor.base import MonitorPlugin
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine

if TYPE_CHECKING:
    from stoner_measurement.temperature_control.types import TemperatureEngineState

def _parse_int_list(text: str, default: list[int]) -> list[int]:
    """Parse a comma-separated string of integers, returning *default* on failure."""
    if not text.strip():
        return default
    result: list[int] = []
    seen: set[int] = set()
    for part in text.split(","):
        try:
            val = int(part.strip())
            if val >= 1 and val not in seen:
                result.append(val)
                seen.add(val)
        except ValueError:
            pass
    return result if result else default


def _parse_channel_list(text: str) -> list[str] | None:
    """Parse a comma-separated channel list, returning ``None`` when blank."""
    if not text.strip():
        return None
    channels: list[str] = []
    seen: set[str] = set()
    for part in text.split(","):
        ch = part.strip()
        if ch and ch not in seen:
            channels.append(ch)
            seen.add(ch)
    return channels if channels else None


class TemperatureMonitorPlugin(MonitorPlugin):
    """Publish live temperature-controller readings into the sequence value catalogue.

    Use this monitor when you want the sequence to have access to live
    temperatures, setpoints, heater outputs, rates of change, and stability
    flags from the temperature-controller engine. The selected quantities are
    added to the sequence value catalogue and can then be plotted, saved,
    displayed, or used by other sequence steps.

    In the configuration panel, choose which control loops and sensor channels
    should be monitored, and then select which quantities to report. You can
    enable any combination of:

    * **Setpoint**
    * **Temperature**
    * **Heater**
    * **Rate of change**
    * **Stability**

    The configuration tab includes text fields for the control-loop list and
    sensor-channel list, together with check boxes for each reported quantity.
    A blank sensor-channel list means all channels currently known to the
    temperature-controller engine. A **force fresh poll** option is also
    available when each read should explicitly refresh the controller state.

    For more technical use, the selected parameters are exposed both via
    :meth:`read` / :attr:`last_reading` and as typed accessor methods on the instance itself
    (:meth:`setpoint`, :meth:`temperature`, :meth:`heater`,
    :meth:`rate`, :meth:`stable`) so that they can be referenced directly in
    sequence scripts.

    Attributes:
        driver_name (str):
            Registered instrument driver name.
        transport_name (str):
            Transport type: ``"Serial"``, ``"GPIB"``, ``"Ethernet"``, or
            ``"Null (test)"``.
        address (str):
            Transport address string.
        control_loops (list[int]):
            Control loop numbers whose setpoint, heater output, and stability are
            reported.  Defaults to ``[1]``.
        sensor_channels (list[str] | None):
            Sensor channel identifiers whose temperature and rate-of-change are
            reported.  ``None`` reports all channels currently known to the engine.
        report_setpoints (bool):
            When ``True``, setpoint values are included in every reading.
        report_temperatures (bool):
            When ``True``, sensor temperatures are included in every reading.
        report_heater (bool):
            When ``True``, heater output percentages are included in every reading.
        report_rate (bool):
            When ``True``, rates of change are included in every reading.
        report_stability (bool):
            When ``True``, stability flags (0.0 / 1.0) are included in every reading.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
        >>> m = TemperatureMonitorPlugin()
        >>> m.name
        'Temperature Monitor'
        >>> m.plugin_type
        'monitor'
        >>> m.report_setpoints
        True
        >>> m.report_temperatures
        True
    """

    def __init__(self, parent=None) -> None:
        """Initialise the plugin with default settings."""
        super().__init__(parent)
        self.control_loops: list[int] = [1]
        self.sensor_channels: list[str] | None = None
        self.report_setpoints: bool = True
        self.report_temperatures: bool = True
        self.report_heater: bool = True
        self.report_rate: bool = True
        self.report_stability: bool = True
        self.force_fresh_poll: bool = False
        self._apply_initial_config()

    # ------------------------------------------------------------------
    # BasePlugin identity
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Plugin display name.

        Returns:
            (str):
                Always ``"Temperature Monitor"``.
        """
        return "Temperature Monitor"

    # ------------------------------------------------------------------
    # Engine helpers
    # ------------------------------------------------------------------

    def _engine(self) -> TemperatureControllerEngine:
        """Return the singleton temperature controller engine."""
        return TemperatureControllerEngine.instance()

    def _refresh_catalogs(self) -> None:
        if self.sequence_engine is not None:
            self.sequence_engine._rebuild_data_catalogs()  # noqa: SLF001

    def _ensure_connected(self) -> TemperatureControllerEngine:
        """Return the shared engine if a controller is already connected.

        Returns:
            (TemperatureControllerEngine):
                The connected engine.

        Raises:
            RuntimeError:
                If no temperature controller is connected.
        """
        engine = self._engine()
        if engine.connected_driver is None:
            raise RuntimeError("No temperature controller is connected.")
        return engine

    def _current_state(self) -> TemperatureEngineState:
        """Return the engine's latest published state."""
        return self._engine().get_engine_state()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Ensure the engine is connected and start the polling timer.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> m.transport_name = "Null (test)"
            >>> m.driver_name = ""
            >>> try:
            ...     m.connect()
            ... except RuntimeError:
            ...     pass
        """
        self._ensure_connected()
        self.start_monitoring()

    def configure(self) -> None:
        """No-op — the engine is configured by dedicated state-control plugins."""

    def disconnect(self) -> None:
        """Stop the polling timer; the shared engine is left running."""
        self.stop_monitoring()

    # ------------------------------------------------------------------
    # Parameter helpers — active parameter lists
    # ------------------------------------------------------------------

    def _active_channels(self) -> list[str]:
        """Return the sensor channels to report.

        Returns:
            (list[str]):
                Explicitly configured channels, or all channels currently known
                to the engine when :attr:`sensor_channels` is ``None``.
        """
        if self.sensor_channels is not None:
            return list(self.sensor_channels)
        state = self._current_state()
        if state.readings:
            return sorted(state.readings)
        driver = self._engine().connected_driver
        if driver is None:
            return []
        try:
            return list(driver.get_capabilities().input_channels)
        except Exception:
            return []

    def _active_loops(self) -> list[int]:
        """Return the control loops to report.

        Returns:
            (list[int]):
                :attr:`control_loops` list, falling back to loops currently
                known to the engine when the configured list is empty.
        """
        if self.control_loops:
            return list(self.control_loops)
        state = self._current_state()
        if state.setpoints:
            return sorted(state.setpoints)
        return [1]

    # ------------------------------------------------------------------
    # MonitorPlugin abstract interface
    # ------------------------------------------------------------------

    @property
    def quantity_names(self) -> list[str]:
        """Ordered list of parameter keys returned by :meth:`read`.

        The list is built dynamically from the current configuration and the
        engine's known channels and loops.

        Returns:
            (list[str]):
                Parameter identifiers.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> m.sensor_channels = ["A"]
            >>> m.control_loops = [1]
            >>> names = m.quantity_names
            >>> "setpoint_1" in names
            True
            >>> "temperature_A" in names
            True
        """
        names: list[str] = []
        channels = self._active_channels()
        loops = self._active_loops()
        if self.report_setpoints:
            for lp in loops:
                names.append(f"setpoint_{lp}")
        if self.report_temperatures:
            for ch in channels:
                names.append(f"temperature_{ch}")
        if self.report_heater:
            for lp in loops:
                names.append(f"heater_{lp}")
        if self.report_rate:
            for ch in channels:
                names.append(f"rate_{ch}")
        if self.report_stability:
            for lp in loops:
                names.append(f"stable_{lp}")
        return names

    @property
    def units(self) -> dict[str, str]:
        """Mapping of parameter name to physical unit string.

        Returns:
            (dict[str, str]):
                Unit strings for each parameter.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> m.sensor_channels = ["A"]
            >>> m.control_loops = [1]
            >>> m.units["setpoint_1"]
            'K'
            >>> m.units["heater_1"]
            '%'
        """
        result: dict[str, str] = {}
        channels = self._active_channels()
        loops = self._active_loops()
        if self.report_setpoints:
            for lp in loops:
                result[f"setpoint_{lp}"] = "K"
        if self.report_temperatures:
            for ch in channels:
                result[f"temperature_{ch}"] = "K"
        if self.report_heater:
            for lp in loops:
                result[f"heater_{lp}"] = "%"
        if self.report_rate:
            for ch in channels:
                result[f"rate_{ch}"] = "K/min"
        if self.report_stability:
            for lp in loops:
                result[f"stable_{lp}"] = ""
        return result

    def read(self, *, force_poll: bool = False) -> dict[str, float]:
        """Read the latest parameter snapshot from the engine.

        By default retrieves the engine's cached state without issuing additional
        hardware queries.  When *force_poll* is ``True`` the engine performs an
        immediate hardware poll and the freshly read state is used, making the
        call synchronous with the hardware.

        Keyword Parameters:
            force_poll (bool):
                When ``True``, requests an immediate hardware poll from the
                engine before returning values.  Defaults to ``False``.

        Returns:
            (dict[str, float]):
                Mapping of parameter name to current value.  Returns
                ``math.nan`` for any parameter that cannot be obtained from
                the engine state.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> m.sensor_channels = ["A"]
            >>> m.control_loops = [1]
            >>> reading = m.read()
            >>> "setpoint_1" in reading
            True
            >>> reading_forced = m.read(force_poll=True)
            >>> "setpoint_1" in reading_forced
            True
        """
        if force_poll or self.force_fresh_poll:
            polled = self._engine().read_controller_state()
            state = polled if polled is not None else self._current_state()
        else:
            state = self._current_state()
        result: dict[str, float] = {}
        channels = self._active_channels()
        loops = self._active_loops()

        if self.report_setpoints:
            for lp in loops:
                result[f"setpoint_{lp}"] = float(state.setpoints.get(lp, math.nan))

        if self.report_temperatures:
            for ch in channels:
                reading = state.readings.get(ch)
                result[f"temperature_{ch}"] = float(reading.value) if reading is not None else math.nan

        if self.report_heater:
            for lp in loops:
                result[f"heater_{lp}"] = float(state.heater_outputs.get(lp, math.nan))

        if self.report_rate:
            for ch in channels:
                reading = state.readings.get(ch)
                result[f"rate_{ch}"] = float(reading.rate_of_change) if reading is not None else math.nan

        if self.report_stability:
            for lp in loops:
                stable_val = state.stable.get(lp)
                result[f"stable_{lp}"] = math.nan if stable_val is None else (1.0 if stable_val else 0.0)

        self._last_reading = result
        return result

    # ------------------------------------------------------------------
    # Typed accessor methods (expose parameters as instance attributes)
    # ------------------------------------------------------------------

    def setpoint(self, loop: int) -> float:
        """Return the current setpoint for *loop* in Kelvin.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (float):
                Setpoint in Kelvin, or ``math.nan`` when unavailable.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> import math
            >>> math.isnan(m.setpoint(1)) or isinstance(m.setpoint(1), float)
            True
        """
        state = self._current_state()
        val = state.setpoints.get(loop)
        return math.nan if val is None else float(val)

    def temperature(self, channel: str) -> float:
        """Return the current temperature reading for *channel* in Kelvin.

        Args:
            channel (str):
                Sensor channel identifier (e.g. ``"A"``).

        Returns:
            (float):
                Temperature in Kelvin, or ``math.nan`` when unavailable.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> import math
            >>> math.isnan(m.temperature("A")) or isinstance(m.temperature("A"), float)
            True
        """
        state = self._current_state()
        reading = state.readings.get(channel)
        return math.nan if reading is None else float(reading.value)

    def heater(self, loop: int) -> float:
        """Return the current heater output for *loop* as a percentage (0–100 %).

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (float):
                Heater output percentage, or ``math.nan`` when unavailable.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> import math
            >>> math.isnan(m.heater(1)) or isinstance(m.heater(1), float)
            True
        """
        state = self._current_state()
        val = state.heater_outputs.get(loop)
        return math.nan if val is None else float(val)

    def rate(self, channel: str) -> float:
        """Return the estimated rate of change for *channel* in Kelvin per minute.

        Args:
            channel (str):
                Sensor channel identifier (e.g. ``"A"``).

        Returns:
            (float):
                Rate of change in K/min, or ``math.nan`` when unavailable.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> import math
            >>> math.isnan(m.rate("A")) or isinstance(m.rate("A"), float)
            True
        """
        state = self._current_state()
        reading = state.readings.get(channel)
        return math.nan if reading is None else float(reading.rate_of_change)

    def stable(self, loop: int) -> float:
        """Return the stability flag for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (float):
                ``1.0`` when stable, ``0.0`` when unstable, or ``math.nan``
                when unavailable.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> m.stable(1) in (0.0, 1.0)
            True
        """
        state = self._current_state()
        stable_val = state.stable.get(loop)
        return math.nan if stable_val is None else (1.0 if stable_val else 0.0)

    # ------------------------------------------------------------------
    # Sequence namespace integration
    # ------------------------------------------------------------------

    def reported_values(self) -> dict[str, str]:
        """Return a mapping of output names to accessor expressions.

        Each selected parameter is reported as both
        ``"{instance_name}:{label}"`` → ``"{instance_name}.method(args)"``
        so that the sequence engine can add them to the data namespace and
        display them in the output catalogue.

        Returns:
            (dict[str, str]):
                Mapping of ``"{instance_name}:{label}"`` to Python expression.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> m.sensor_channels = ["A"]
            >>> m.control_loops = [1]
            >>> vals = m.reported_values()
            >>> var = m.instance_name
            >>> f"{var}:Setpoint loop 1" in vals
            True
            >>> f"{var}:Temperature A" in vals
            True
        """
        var = self.instance_name
        values: dict[str, str] = {}
        channels = self._active_channels()
        loops = self._active_loops()

        if self.report_setpoints:
            for lp in loops:
                values[f"{var}:Setpoint loop {lp}"] = f"{var}.setpoint({lp!r})"

        if self.report_temperatures:
            for ch in channels:
                values[f"{var}:Temperature {ch}"] = f"{var}.temperature({ch!r})"

        if self.report_heater:
            for lp in loops:
                values[f"{var}:Heater loop {lp}"] = f"{var}.heater({lp!r})"

        if self.report_rate:
            for ch in channels:
                values[f"{var}:Rate {ch}"] = f"{var}.rate({ch!r})"

        if self.report_stability:
            for lp in loops:
                values[f"{var}:Stable loop {lp}"] = f"{var}.stable({lp!r})"

        return values

    # ------------------------------------------------------------------
    # JSON serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> dict[str, object]:
        """Serialise plugin configuration to a JSON-compatible dict.

        Returns:
            (dict[str, object]):
                Serialised configuration.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> d = m.to_json()
            >>> d["report_setpoints"]
            True
            >>> "driver_name" in d
            True
        """
        data = super().to_json()
        data.update(
            {
                "control_loops": list(self.control_loops),
                "sensor_channels": None if self.sensor_channels is None else list(self.sensor_channels),
                "report_setpoints": self.report_setpoints,
                "report_temperatures": self.report_temperatures,
                "report_heater": self.report_heater,
                "report_rate": self.report_rate,
                "report_stability": self.report_stability,
                "force_fresh_poll": self.force_fresh_poll,
            }
        )
        return data

    def _restore_from_json(self, data: dict[str, object]) -> None:
        """Restore plugin settings from a serialised dict.

        Args:
            data (dict[str, object]):
                Serialised configuration as produced by :meth:`to_json`.
        """
        if "control_loops" in data:
            raw = data["control_loops"]
            if isinstance(raw, list):
                loops: list[int] = []
                seen: set[int] = set()
                for value in raw:
                    try:
                        iv = int(value)
                    except (TypeError, ValueError):
                        continue
                    if iv >= 1 and iv not in seen:
                        loops.append(iv)
                        seen.add(iv)
                self.control_loops = loops if loops else [1]
            else:
                self.control_loops = [1]
        if "sensor_channels" in data:
            raw = data["sensor_channels"]
            self.sensor_channels = (
                _parse_channel_list(", ".join(str(value) for value in raw if value is not None))
                if isinstance(raw, list)
                else None
            )
        if "report_setpoints" in data:
            self.report_setpoints = bool(data["report_setpoints"])
        if "report_temperatures" in data:
            self.report_temperatures = bool(data["report_temperatures"])
        if "report_heater" in data:
            self.report_heater = bool(data["report_heater"])
        if "report_rate" in data:
            self.report_rate = bool(data["report_rate"])
        if "report_stability" in data:
            self.report_stability = bool(data["report_stability"])
        if "force_fresh_poll" in data:
            self.force_fresh_poll = bool(data["force_fresh_poll"])

    # ------------------------------------------------------------------
    # Configuration widget
    # ------------------------------------------------------------------

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return the configuration widget for this plugin.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                Configuration widget with all plugin settings.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
            >>> m = TemperatureMonitorPlugin()
            >>> w = m.config_widget()
            >>> w is not None
            True
        """
        return _TemperatureMonitorSettingsWidget(self, parent=parent)


class _TemperatureMonitorSettingsWidget(QWidget):
    """Configuration widget for :class:`TemperatureMonitorPlugin`."""

    def __init__(self, plugin: TemperatureMonitorPlugin, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plugin = plugin
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ---- Channel / loop selection group ---------------------------------
        sel_group = QGroupBox("Channels & Loops", self)
        sel_form = QFormLayout(sel_group)

        loops_text = ", ".join(str(lp) for lp in self._plugin.control_loops)
        self._loops_edit = QLineEdit(loops_text, sel_group)
        self._loops_edit.setPlaceholderText("Comma-separated loop numbers, e.g. 1, 2")
        self._loops_edit.editingFinished.connect(self._on_loops_changed)
        sel_form.addRow("Control loops:", self._loops_edit)

        channels_text = "" if self._plugin.sensor_channels is None else ", ".join(self._plugin.sensor_channels)
        self._channels_edit = QLineEdit(channels_text, sel_group)
        self._channels_edit.setPlaceholderText("Comma-separated sensor channels; blank = all available")
        self._channels_edit.editingFinished.connect(self._on_channels_changed)
        sel_form.addRow("Sensor channels:", self._channels_edit)

        root.addWidget(sel_group)

        # ---- Parameter selection group --------------------------------------
        param_group = QGroupBox("Report parameters", self)
        param_form = QFormLayout(param_group)

        self._cb_setpoints = QCheckBox(param_group)
        self._cb_setpoints.setChecked(self._plugin.report_setpoints)
        self._cb_setpoints.toggled.connect(self._on_setpoints_toggled)
        param_form.addRow("Setpoints:", self._cb_setpoints)

        self._cb_temperatures = QCheckBox(param_group)
        self._cb_temperatures.setChecked(self._plugin.report_temperatures)
        self._cb_temperatures.toggled.connect(self._on_temperatures_toggled)
        param_form.addRow("Temperatures:", self._cb_temperatures)

        self._cb_heater = QCheckBox(param_group)
        self._cb_heater.setChecked(self._plugin.report_heater)
        self._cb_heater.toggled.connect(self._on_heater_toggled)
        param_form.addRow("Heater outputs:", self._cb_heater)

        self._cb_rate = QCheckBox(param_group)
        self._cb_rate.setChecked(self._plugin.report_rate)
        self._cb_rate.toggled.connect(self._on_rate_toggled)
        param_form.addRow("Rates of change:", self._cb_rate)

        self._cb_stability = QCheckBox(param_group)
        self._cb_stability.setChecked(self._plugin.report_stability)
        self._cb_stability.toggled.connect(self._on_stability_toggled)
        param_form.addRow("Stability flags:", self._cb_stability)

        self._cb_force_poll = QCheckBox(param_group)
        self._cb_force_poll.setChecked(self._plugin.force_fresh_poll)
        self._cb_force_poll.toggled.connect(self._on_force_poll_toggled)
        param_form.addRow("Force fresh controller poll:", self._cb_force_poll)

        root.addWidget(param_group)
        root.addStretch(1)

    # ---- Slots ---------------------------------------------------------------

    def _on_loops_changed(self) -> None:
        text = self._loops_edit.text()
        self._plugin.control_loops = _parse_int_list(text, [1])
        self._plugin._refresh_catalogs()

    def _on_channels_changed(self) -> None:
        text = self._channels_edit.text()
        self._plugin.sensor_channels = _parse_channel_list(text)
        self._plugin._refresh_catalogs()

    def _on_setpoints_toggled(self, checked: bool) -> None:
        self._plugin.report_setpoints = checked
        self._plugin._refresh_catalogs()

    def _on_temperatures_toggled(self, checked: bool) -> None:
        self._plugin.report_temperatures = checked
        self._plugin._refresh_catalogs()

    def _on_heater_toggled(self, checked: bool) -> None:
        self._plugin.report_heater = checked
        self._plugin._refresh_catalogs()

    def _on_rate_toggled(self, checked: bool) -> None:
        self._plugin.report_rate = checked
        self._plugin._refresh_catalogs()

    def _on_stability_toggled(self, checked: bool) -> None:
        self._plugin.report_stability = checked
        self._plugin._refresh_catalogs()

    def _on_force_poll_toggled(self, checked: bool) -> None:
        self._plugin.force_fresh_poll = checked
        self._plugin._refresh_catalogs()
