"""Pressure controller monitor plugin."""

from __future__ import annotations

import math

from qtpy.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.plugins.monitor.base import MonitorPlugin
from stoner_measurement.pressure_control.engine import PressureControllerEngine


def _parse_int_list(text: str) -> list[int] | None:
    """Parse a comma-separated integer list, returning ``None`` when blank."""
    if not text.strip():
        return None
    result: list[int] = []
    seen: set[int] = set()
    for part in text.split(","):
        try:
            value = int(part.strip())
        except ValueError:
            continue
        if value >= 1 and value not in seen:
            result.append(value)
            seen.add(value)
    return result or None


class PressureMonitorPlugin(MonitorPlugin):
    """Publish live pressure-controller and MFC values into the sequence namespace."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.pressure_channels: list[int] | None = None
        self.mfc_channels: list[int] | None = None
        self.report_pressures: bool = True
        self.report_flow_setpoints: bool = True
        self.report_flow_actual: bool = True
        self.report_target_pressures: bool = True
        self.report_gauge_enabled: bool = True
        self.force_fresh_poll: bool = False
        self._apply_initial_config()

    @property
    def name(self) -> str:
        return "Pressure Monitor"

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"pressure"})

    def _engine(self) -> PressureControllerEngine:
        return PressureControllerEngine.instance()

    def _refresh_catalogs(self) -> None:
        if self.sequence_engine is not None:
            self.sequence_engine._rebuild_data_catalogs()  # noqa: SLF001

    def _ensure_connected(self) -> PressureControllerEngine:
        engine = self._engine()
        if engine.connected_driver is None and engine.preferred_driver_name:
            engine.connect_preferred_driver()
        if engine.connected_mfc_driver is None and engine.preferred_mfc_driver_name:
            engine.connect_preferred_mfc_driver()
        if engine.connected_driver is None and engine.connected_mfc_driver is None:
            raise RuntimeError("No pressure controller or mass flow controller is connected.")
        return engine

    def _current_state(self):
        return self._engine().get_engine_state()

    def connect(self) -> None:
        self._ensure_connected()
        self.start_monitoring()

    def configure(self) -> None:
        """No-op: the shared pressure engine owns the hardware configuration."""

    def disconnect(self) -> None:
        self.stop_monitoring()

    def _active_pressure_channels(self) -> list[int]:
        if self.pressure_channels is not None:
            return list(self.pressure_channels)
        state = self._current_state()
        if state.readings:
            return sorted(state.readings)
        return []

    def _active_mfc_channels(self) -> list[int]:
        if self.mfc_channels is not None:
            return list(self.mfc_channels)
        state = self._current_state()
        if state.flow_actual:
            return sorted(state.flow_actual)
        if state.flow_setpoints:
            return sorted(state.flow_setpoints)
        return []

    @property
    def quantity_names(self) -> list[str]:
        names: list[str] = []
        if self.report_pressures:
            for channel in self._active_pressure_channels():
                names.append(f"pressure_{channel}")
        if self.report_gauge_enabled:
            for channel in self._active_pressure_channels():
                names.append(f"gauge_enabled_{channel}")
        if self.report_flow_setpoints:
            for channel in self._active_mfc_channels():
                names.append(f"flow_setpoint_{channel}")
        if self.report_flow_actual:
            for channel in self._active_mfc_channels():
                names.append(f"flow_actual_{channel}")
        if self.report_target_pressures:
            for channel in self._active_mfc_channels():
                names.append(f"target_pressure_{channel}")
        return names

    @property
    def units(self) -> dict[str, str]:
        state = self._current_state()
        pressure_unit = ""
        if state.unit is not None:
            pressure_unit = state.unit.value if hasattr(state.unit, "value") else str(state.unit)
        flow_unit = ""
        if state.flow_unit is not None:
            flow_unit = str(state.flow_unit)
        result: dict[str, str] = {}
        for channel in self._active_pressure_channels():
            if self.report_pressures:
                result[f"pressure_{channel}"] = pressure_unit
            if self.report_gauge_enabled:
                result[f"gauge_enabled_{channel}"] = ""
        for channel in self._active_mfc_channels():
            if self.report_flow_setpoints:
                result[f"flow_setpoint_{channel}"] = flow_unit
            if self.report_flow_actual:
                result[f"flow_actual_{channel}"] = flow_unit
            if self.report_target_pressures:
                result[f"target_pressure_{channel}"] = pressure_unit
        return result

    def read(self, *, force_poll: bool = False) -> dict[str, float]:
        if force_poll or self.force_fresh_poll:
            state = self._ensure_connected().read_controller_state() or self._current_state()
        else:
            state = self._current_state()
        result: dict[str, float] = {}
        for channel in self._active_pressure_channels():
            if self.report_pressures:
                reading = state.readings.get(channel)
                result[f"pressure_{channel}"] = (
                    math.nan if reading is None or reading.value is None else float(reading.value)
                )
            if self.report_gauge_enabled:
                enabled = state.gauge_channel_enabled.get(channel)
                result[f"gauge_enabled_{channel}"] = math.nan if enabled is None else (1.0 if enabled else 0.0)
        for channel in self._active_mfc_channels():
            if self.report_flow_setpoints:
                result[f"flow_setpoint_{channel}"] = float(state.flow_setpoints.get(channel, math.nan))
            if self.report_flow_actual:
                result[f"flow_actual_{channel}"] = float(state.flow_actual.get(channel, math.nan))
            if self.report_target_pressures:
                result[f"target_pressure_{channel}"] = float(state.target_pressures.get(channel, math.nan))
        self._last_reading = result
        return result

    def reported_values(self) -> dict[str, str]:
        var = self.instance_name
        return {
            f"{var}:{quantity.replace('_', ' ').title()}": f"{var}.last_reading['{quantity}']"
            for quantity in self.quantity_names
        }

    def to_json(self) -> dict[str, object]:
        data = super().to_json()
        data.update(
            {
                "pressure_channels": self.pressure_channels,
                "mfc_channels": self.mfc_channels,
                "report_pressures": self.report_pressures,
                "report_flow_setpoints": self.report_flow_setpoints,
                "report_flow_actual": self.report_flow_actual,
                "report_target_pressures": self.report_target_pressures,
                "report_gauge_enabled": self.report_gauge_enabled,
                "force_fresh_poll": self.force_fresh_poll,
            }
        )
        return data

    def _restore_from_json(self, data: dict[str, object]) -> None:
        if isinstance(data.get("pressure_channels"), list):
            self.pressure_channels = [int(value) for value in data["pressure_channels"]]
        if isinstance(data.get("mfc_channels"), list):
            self.mfc_channels = [int(value) for value in data["mfc_channels"]]
        for key in (
            "report_pressures",
            "report_flow_setpoints",
            "report_flow_actual",
            "report_target_pressures",
            "report_gauge_enabled",
            "force_fresh_poll",
        ):
            if key in data:
                setattr(self, key, bool(data[key]))

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        return _PressureMonitorSettingsWidget(self, parent=parent)


class _PressureMonitorSettingsWidget(QWidget):
    """Configuration widget for :class:`PressureMonitorPlugin`."""

    def __init__(self, plugin: PressureMonitorPlugin, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plugin = plugin
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        select_group = QGroupBox("Channels", self)
        select_form = QFormLayout(select_group)
        pressure_text = "" if self._plugin.pressure_channels is None else ", ".join(map(str, self._plugin.pressure_channels))
        mfc_text = "" if self._plugin.mfc_channels is None else ", ".join(map(str, self._plugin.mfc_channels))
        self._pressure_channels_edit = QLineEdit(pressure_text, select_group)
        self._pressure_channels_edit.setPlaceholderText("Blank = all pressure channels")
        self._pressure_channels_edit.editingFinished.connect(self._on_pressure_channels_changed)
        self._mfc_channels_edit = QLineEdit(mfc_text, select_group)
        self._mfc_channels_edit.setPlaceholderText("Blank = all MFC channels")
        self._mfc_channels_edit.editingFinished.connect(self._on_mfc_channels_changed)
        select_form.addRow("Pressure channels:", self._pressure_channels_edit)
        select_form.addRow("MFC channels:", self._mfc_channels_edit)
        root.addWidget(select_group)

        report_group = QGroupBox("Report parameters", self)
        report_form = QFormLayout(report_group)
        self._cb_pressures = QCheckBox(report_group)
        self._cb_pressures.setChecked(self._plugin.report_pressures)
        self._cb_pressures.toggled.connect(self._on_pressures_toggled)
        report_form.addRow("Pressures:", self._cb_pressures)
        self._cb_gauge_enabled = QCheckBox(report_group)
        self._cb_gauge_enabled.setChecked(self._plugin.report_gauge_enabled)
        self._cb_gauge_enabled.toggled.connect(self._on_gauge_enabled_toggled)
        report_form.addRow("Gauge enabled:", self._cb_gauge_enabled)
        self._cb_flow_setpoints = QCheckBox(report_group)
        self._cb_flow_setpoints.setChecked(self._plugin.report_flow_setpoints)
        self._cb_flow_setpoints.toggled.connect(self._on_flow_setpoints_toggled)
        report_form.addRow("Flow setpoints:", self._cb_flow_setpoints)
        self._cb_flow_actual = QCheckBox(report_group)
        self._cb_flow_actual.setChecked(self._plugin.report_flow_actual)
        self._cb_flow_actual.toggled.connect(self._on_flow_actual_toggled)
        report_form.addRow("Actual flows:", self._cb_flow_actual)
        self._cb_target_pressures = QCheckBox(report_group)
        self._cb_target_pressures.setChecked(self._plugin.report_target_pressures)
        self._cb_target_pressures.toggled.connect(self._on_target_pressures_toggled)
        report_form.addRow("Target pressures:", self._cb_target_pressures)
        self._cb_force_poll = QCheckBox(report_group)
        self._cb_force_poll.setChecked(self._plugin.force_fresh_poll)
        self._cb_force_poll.toggled.connect(self._on_force_poll_toggled)
        report_form.addRow("Force fresh controller poll:", self._cb_force_poll)
        root.addWidget(report_group)
        root.addStretch(1)

    def _on_pressure_channels_changed(self) -> None:
        self._plugin.pressure_channels = _parse_int_list(self._pressure_channels_edit.text())
        self._plugin._refresh_catalogs()

    def _on_mfc_channels_changed(self) -> None:
        self._plugin.mfc_channels = _parse_int_list(self._mfc_channels_edit.text())
        self._plugin._refresh_catalogs()

    def _on_pressures_toggled(self, checked: bool) -> None:
        self._plugin.report_pressures = checked
        self._plugin._refresh_catalogs()

    def _on_gauge_enabled_toggled(self, checked: bool) -> None:
        self._plugin.report_gauge_enabled = checked
        self._plugin._refresh_catalogs()

    def _on_flow_setpoints_toggled(self, checked: bool) -> None:
        self._plugin.report_flow_setpoints = checked
        self._plugin._refresh_catalogs()

    def _on_flow_actual_toggled(self, checked: bool) -> None:
        self._plugin.report_flow_actual = checked
        self._plugin._refresh_catalogs()

    def _on_target_pressures_toggled(self, checked: bool) -> None:
        self._plugin.report_target_pressures = checked
        self._plugin._refresh_catalogs()

    def _on_force_poll_toggled(self, checked: bool) -> None:
        self._plugin.force_fresh_poll = checked
        self._plugin._refresh_catalogs()
