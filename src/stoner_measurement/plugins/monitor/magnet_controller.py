"""Magnetic field controller monitor plugin.

Reads live parameters from the
:class:`~stoner_measurement.magnet_control.engine.MagnetControllerEngine`
and exposes them as output values in the sequence namespace and as attributes
of the plugin instance.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from qtpy.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.plugins.monitor.base import MonitorPlugin

if TYPE_CHECKING:
    from stoner_measurement.magnet_control.types import MagnetEngineState


class MagneticFieldMonitorPlugin(MonitorPlugin):
    """Publish live magnet-controller readings into the sequence value catalogue.

    Use this monitor when you want the sequence to have access to live magnet
    information such as field, current, voltage, ramp rate, heater state, and
    stability. The selected quantities appear in the sequence value catalogue
    and can then be displayed, logged, plotted, saved, or used by other
    plugins.

    In the configuration panel, choose which quantities should be reported.
    You can enable any combination of:

    * **Field**
    * **Target field**
    * **Current**
    * **Voltage**
    * **Field rate**
    * **Heater**
    * **At target**
    * **Stable**

    For more technical use, the selected parameters are exposed both via
    :meth:`read` / :attr:`last_reading` and as typed accessor methods on the instance itself
    (:meth:`field`, :meth:`target_field`, :meth:`current`, :meth:`voltage`,
    :meth:`field_rate`, :meth:`heater`, :meth:`at_target`, :meth:`stable`) so
    that they can be referenced directly in sequence scripts.

    Attributes:
        report_field (bool):
            When ``True``, the measured field is included in every reading.
        report_target_field (bool):
            When ``True``, the target field is included in every reading.
        report_current (bool):
            When ``True``, the magnet current is included in every reading.
        report_voltage (bool):
            When ``True``, the magnet voltage is included in every reading.
        report_field_rate (bool):
            When ``True``, the field rate of change is included in every
            reading.
        report_heater (bool):
            When ``True``, the heater state is included in every reading.
        report_at_target (bool):
            When ``True``, the at-target flag is included in every reading.
        report_stability (bool):
            When ``True``, the stability flag is included in every reading.
        force_fresh_poll (bool):
            When ``True``, every call to :meth:`read` requests an immediate
            hardware poll from the engine rather than relying solely on the
            cached engine state.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.monitor.magnet_controller import MagneticFieldMonitorPlugin
        >>> m = MagneticFieldMonitorPlugin()
        >>> m.name
        'Magnetic Field Monitor'
        >>> m.plugin_type
        'monitor'
        >>> m.report_field
        True
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.report_field: bool = True
        self.report_target_field: bool = True
        self.report_current: bool = True
        self.report_voltage: bool = True
        self.report_field_rate: bool = True
        self.report_heater: bool = True
        self.report_at_target: bool = True
        self.report_stability: bool = True
        self.force_fresh_poll: bool = False
        self._apply_initial_config()

    @property
    def name(self) -> str:
        return "Magnetic Field Monitor"

    def _engine(self) -> MagnetControllerEngine:
        return MagnetControllerEngine.instance()

    def _refresh_catalogs(self) -> None:
        if self.sequence_engine is not None:
            self.sequence_engine._rebuild_data_catalogs()  # noqa: SLF001

    def _ensure_connected(self) -> MagnetControllerEngine:
        """Return the shared engine if a controller is connected."""
        engine = self._engine()
        if engine.connected_driver is None:
            raise RuntimeError("No magnet controller is connected.")
        return engine

    def _current_state(self) -> MagnetEngineState:
        """Return the engine's latest published state."""
        return self._engine().get_engine_state()

    def _raise_if_quenched(self, state: MagnetEngineState) -> None:
        """Raise to stop scripts when the magnet controller reports a quench."""
        if state.reading is not None and state.reading.quench_detected:
            raise RuntimeError("Magnet controller reported a quench condition.")

    def connect(self) -> None:
        """Ensure the engine is connected and start the polling timer.

        Raises:
            RuntimeError:
                If no magnet controller is connected.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.magnet_controller import MagneticFieldMonitorPlugin
            >>> m = MagneticFieldMonitorPlugin()
            >>> try:
            ...     m.connect()
            ... except RuntimeError:
            ...     pass
        """
        self._raise_if_quenched(self._current_state())
        self._ensure_connected()
        self.start_monitoring()

    def configure(self) -> None:
        """No-op — the engine is configured by dedicated state-control plugins."""

    def disconnect(self) -> None:
        """Stop the polling timer; the shared engine is left running.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.magnet_controller import MagneticFieldMonitorPlugin
            >>> m = MagneticFieldMonitorPlugin()
            >>> m.stop_monitoring()
            >>> m.disconnect()
        """
        self.stop_monitoring()

    @property
    def quantity_names(self) -> list[str]:
        """Ordered list of parameter keys returned by :meth:`read`.

        Returns:
            (list[str]):
                Parameter identifiers for all currently enabled outputs.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.magnet_controller import MagneticFieldMonitorPlugin
            >>> m = MagneticFieldMonitorPlugin()
            >>> "field" in m.quantity_names
            True
        """
        names = []
        if self.report_field:
            names.append("field")
        if self.report_target_field:
            names.append("target_field")
        if self.report_current:
            names.append("current")
        if self.report_voltage:
            names.append("voltage")
        if self.report_field_rate:
            names.append("field_rate")
        if self.report_heater:
            names.append("heater")
        if self.report_at_target:
            names.append("at_target")
        if self.report_stability:
            names.append("stable")
        return names

    @property
    def units(self) -> dict[str, str]:
        """Mapping of parameter name to physical unit string.

        Returns:
            (dict[str, str]):
                Unit strings for each enabled parameter.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.magnet_controller import MagneticFieldMonitorPlugin
            >>> m = MagneticFieldMonitorPlugin()
            >>> m.units["field"]
            'T'
            >>> m.units["current"]
            'A'
        """
        units = {}
        if self.report_field:
            units["field"] = "T"
        if self.report_target_field:
            units["target_field"] = "T"
        if self.report_current:
            units["current"] = "A"
        if self.report_voltage:
            units["voltage"] = "V"
        if self.report_field_rate:
            units["field_rate"] = "T/min"
        if self.report_heater:
            units["heater"] = ""
        if self.report_at_target:
            units["at_target"] = ""
        if self.report_stability:
            units["stable"] = ""
        return units

    def read(self, *, force_poll: bool = False) -> dict[str, float]:
        """Read the latest parameter snapshot from the engine.

        By default retrieves the engine's cached state without issuing
        additional hardware queries. When *force_poll* is ``True`` the engine
        performs an immediate hardware poll and the freshly read state is used,
        making the call synchronous with the hardware.

        Keyword Parameters:
            force_poll (bool):
                When ``True``, requests an immediate hardware poll from the
                engine before returning values. Defaults to ``False``.

        Returns:
            (dict[str, float]):
                Mapping of parameter name to current value. Returns
                ``math.nan`` for any parameter that cannot be obtained from
                the engine state.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.magnet_controller import MagneticFieldMonitorPlugin
            >>> m = MagneticFieldMonitorPlugin()
            >>> reading = m.read()
            >>> "field" in reading
            True
            >>> reading_forced = m.read(force_poll=True)
            >>> "field" in reading_forced
            True
        """
        if force_poll or self.force_fresh_poll:
            state = self._engine().read_controller_state() or self._current_state()
        else:
            state = self._current_state()

        self._raise_if_quenched(state)
        reading = state.reading
        result: dict[str, float] = {}

        if self.report_field:
            result["field"] = math.nan if reading is None or reading.field is None else float(reading.field)
        if self.report_target_field:
            result["target_field"] = (
                math.nan if state.target_field is None else float(state.target_field)
            )
        if self.report_current:
            result["current"] = math.nan if reading is None else float(reading.current)
        if self.report_voltage:
            result["voltage"] = (
                math.nan if reading is None or reading.voltage is None else float(reading.voltage)
            )
        if self.report_field_rate:
            result["field_rate"] = math.nan if reading is None else float(reading.field_rate)
        if self.report_heater:
            result["heater"] = (
                math.nan
                if reading is None or reading.heater_on is None
                else (1.0 if reading.heater_on else 0.0)
            )
        if self.report_at_target:
            result["at_target"] = 1.0 if state.at_target else 0.0
        if self.report_stability:
            result["stable"] = 1.0 if state.stable else 0.0

        self._last_reading = result
        return result

    def field(self) -> float:
        """Return the current magnetic field in tesla.

        Returns:
            (float):
                Magnetic field in tesla, or ``math.nan`` when unavailable.
        """
        state = self._current_state()
        self._raise_if_quenched(state)
        reading = state.reading
        return math.nan if reading is None or reading.field is None else float(reading.field)

    def target_field(self) -> float:
        """Return the current target magnetic field in tesla.

        Returns:
            (float):
                Target magnetic field in tesla, or ``math.nan`` when
                unavailable.
        """
        state = self._current_state()
        self._raise_if_quenched(state)
        value = state.target_field
        return math.nan if value is None else float(value)

    def current(self) -> float:
        """Return the current magnet current in amps.

        Returns:
            (float):
                Magnet current in amps, or ``math.nan`` when unavailable.
        """
        state = self._current_state()
        self._raise_if_quenched(state)
        reading = state.reading
        return math.nan if reading is None else float(reading.current)

    def voltage(self) -> float:
        """Return the current magnet voltage in volts.

        Returns:
            (float):
                Magnet voltage in volts, or ``math.nan`` when unavailable.
        """
        state = self._current_state()
        self._raise_if_quenched(state)
        reading = state.reading
        return math.nan if reading is None or reading.voltage is None else float(reading.voltage)

    def field_rate(self) -> float:
        """Return the field ramp rate in tesla per minute.

        Returns:
            (float):
                Field ramp rate in T/min, or ``math.nan`` when unavailable.
        """
        state = self._current_state()
        self._raise_if_quenched(state)
        reading = state.reading
        return math.nan if reading is None else float(reading.field_rate)

    def heater(self) -> float:
        """Return the persistent-switch heater state.

        Returns:
            (float):
                ``1.0`` when the heater is on, ``0.0`` when it is off, or
                ``math.nan`` when unavailable.
        """
        state = self._current_state()
        self._raise_if_quenched(state)
        reading = state.reading
        if reading is None or reading.heater_on is None:
            return math.nan
        return 1.0 if reading.heater_on else 0.0

    def at_target(self) -> float:
        """Return whether the magnet is at its target field.

        Returns:
            (float):
                ``1.0`` when at target or ``0.0`` otherwise.
        """
        state = self._current_state()
        self._raise_if_quenched(state)
        return 1.0 if state.at_target else 0.0

    def stable(self) -> float:
        """Return whether the magnetic field is stable.

        Returns:
            (float):
                ``1.0`` when stable or ``0.0`` otherwise.
        """
        state = self._current_state()
        self._raise_if_quenched(state)
        return 1.0 if state.stable else 0.0

    def reported_values(self) -> dict[str, str]:
        """Return a mapping of output names to accessor expressions.

        Each selected parameter is reported as both
        ``"{instance_name}:{label}"`` → ``"{instance_name}.method()"`` so
        that the sequence engine can add them to the data namespace and
        display them in the output catalogue.

        Returns:
            (dict[str, str]):
                Mapping of ``"{instance_name}:{label}"`` to Python expression.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.magnet_controller import MagneticFieldMonitorPlugin
            >>> m = MagneticFieldMonitorPlugin()
            >>> vals = m.reported_values()
            >>> var = m.instance_name
            >>> f"{var}:Field" in vals
            True
            >>> f"{var}:Current" in vals
            True
        """
        var = self.instance_name
        values: dict[str, str] = {}

        if self.report_field:
            values[f"{var}:Field"] = f"{var}.field()"
        if self.report_target_field:
            values[f"{var}:Target Field"] = f"{var}.target_field()"
        if self.report_current:
            values[f"{var}:Current"] = f"{var}.current()"
        if self.report_voltage:
            values[f"{var}:Voltage"] = f"{var}.voltage()"
        if self.report_field_rate:
            values[f"{var}:Field Rate"] = f"{var}.field_rate()"
        if self.report_heater:
            values[f"{var}:Heater"] = f"{var}.heater()"
        if self.report_at_target:
            values[f"{var}:At Target"] = f"{var}.at_target()"
        if self.report_stability:
            values[f"{var}:Stable"] = f"{var}.stable()"

        return values

    def to_json(self) -> dict[str, object]:
        """Serialise plugin configuration to a JSON-compatible dict.

        Returns:
            (dict[str, object]):
                Serialised configuration.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.monitor.magnet_controller import MagneticFieldMonitorPlugin
            >>> m = MagneticFieldMonitorPlugin()
            >>> d = m.to_json()
            >>> d["report_field"]
            True
        """
        data = super().to_json()
        data.update(
            {
                "report_field": self.report_field,
                "report_target_field": self.report_target_field,
                "report_current": self.report_current,
                "report_voltage": self.report_voltage,
                "report_field_rate": self.report_field_rate,
                "report_heater": self.report_heater,
                "report_at_target": self.report_at_target,
                "report_stability": self.report_stability,
                "force_fresh_poll": self.force_fresh_poll,
            }
        )
        return data

    def _restore_from_json(self, data: dict[str, object]) -> None:
        """Restore plugin settings from a serialised dict."""
        for key in (
            "report_field",
            "report_target_field",
            "report_current",
            "report_voltage",
            "report_field_rate",
            "report_heater",
            "report_at_target",
            "report_stability",
            "force_fresh_poll",
        ):
            if key in data:
                setattr(self, key, bool(data[key]))
        self._refresh_catalogs()

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
            >>> from stoner_measurement.plugins.monitor.magnet_controller import MagneticFieldMonitorPlugin
            >>> m = MagneticFieldMonitorPlugin()
            >>> w = m.config_widget()
            >>> w is not None
            True
        """
        return _MagneticFieldMonitorSettingsWidget(self, parent=parent)


class _MagneticFieldMonitorSettingsWidget(QWidget):
    """Configuration widget for :class:`MagneticFieldMonitorPlugin`."""

    def __init__(
        self,
        plugin: MagneticFieldMonitorPlugin,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plugin = plugin

        layout = QVBoxLayout(self)
        group = QGroupBox("Report parameters", self)
        form = QFormLayout(group)

        self._cb_field = QCheckBox(group)
        self._cb_field.setChecked(self._plugin.report_field)
        self._cb_field.toggled.connect(self._on_field_toggled)
        form.addRow("Field:", self._cb_field)

        self._cb_target_field = QCheckBox(group)
        self._cb_target_field.setChecked(self._plugin.report_target_field)
        self._cb_target_field.toggled.connect(self._on_target_field_toggled)
        form.addRow("Target field:", self._cb_target_field)

        self._cb_current = QCheckBox(group)
        self._cb_current.setChecked(self._plugin.report_current)
        self._cb_current.toggled.connect(self._on_current_toggled)
        form.addRow("Current:", self._cb_current)

        self._cb_voltage = QCheckBox(group)
        self._cb_voltage.setChecked(self._plugin.report_voltage)
        self._cb_voltage.toggled.connect(self._on_voltage_toggled)
        form.addRow("Voltage:", self._cb_voltage)

        self._cb_field_rate = QCheckBox(group)
        self._cb_field_rate.setChecked(self._plugin.report_field_rate)
        self._cb_field_rate.toggled.connect(self._on_field_rate_toggled)
        form.addRow("Field rate:", self._cb_field_rate)

        self._cb_heater = QCheckBox(group)
        self._cb_heater.setChecked(self._plugin.report_heater)
        self._cb_heater.toggled.connect(self._on_heater_toggled)
        form.addRow("Heater state:", self._cb_heater)

        self._cb_at_target = QCheckBox(group)
        self._cb_at_target.setChecked(self._plugin.report_at_target)
        self._cb_at_target.toggled.connect(self._on_at_target_toggled)
        form.addRow("At target:", self._cb_at_target)

        self._cb_stability = QCheckBox(group)
        self._cb_stability.setChecked(self._plugin.report_stability)
        self._cb_stability.toggled.connect(self._on_stability_toggled)
        form.addRow("Stability:", self._cb_stability)

        self._cb_force_poll = QCheckBox(group)
        self._cb_force_poll.setChecked(self._plugin.force_fresh_poll)
        self._cb_force_poll.toggled.connect(self._on_force_poll_toggled)
        form.addRow("Force fresh controller poll:", self._cb_force_poll)

        layout.addWidget(group)
        layout.addStretch(1)

    def _on_field_toggled(self, checked: bool) -> None:
        self._plugin.report_field = checked
        self._plugin._refresh_catalogs()

    def _on_target_field_toggled(self, checked: bool) -> None:
        self._plugin.report_target_field = checked
        self._plugin._refresh_catalogs()

    def _on_current_toggled(self, checked: bool) -> None:
        self._plugin.report_current = checked
        self._plugin._refresh_catalogs()

    def _on_voltage_toggled(self, checked: bool) -> None:
        self._plugin.report_voltage = checked
        self._plugin._refresh_catalogs()

    def _on_field_rate_toggled(self, checked: bool) -> None:
        self._plugin.report_field_rate = checked
        self._plugin._refresh_catalogs()

    def _on_heater_toggled(self, checked: bool) -> None:
        self._plugin.report_heater = checked
        self._plugin._refresh_catalogs()

    def _on_at_target_toggled(self, checked: bool) -> None:
        self._plugin.report_at_target = checked
        self._plugin._refresh_catalogs()

    def _on_stability_toggled(self, checked: bool) -> None:
        self._plugin.report_stability = checked
        self._plugin._refresh_catalogs()

    def _on_force_poll_toggled(self, checked: bool) -> None:
        self._plugin.force_fresh_poll = checked
        self._plugin._refresh_catalogs()