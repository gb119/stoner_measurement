"""Motor controller monitor plugin."""

from __future__ import annotations

import math

from qtpy.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.motor_control.engine import MotorControllerEngine
from stoner_measurement.plugins.monitor.base import MonitorPlugin


class MotorAngleMonitorPlugin(MonitorPlugin):
    """Publish live motor-controller readings into the sequence value catalogue."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.report_angle: bool = True
        self.report_target_angle: bool = True
        self.report_moving: bool = True
        self.report_angular_rate: bool = True
        self.report_at_target: bool = True
        self.report_stability: bool = True
        self.force_fresh_poll: bool = False
        self._apply_initial_config()

    @property
    def name(self) -> str:
        return "Motor Angle Monitor"

    def _engine(self) -> MotorControllerEngine:
        return MotorControllerEngine.instance()

    def _refresh_catalogs(self) -> None:
        if self.sequence_engine is not None:
            self.sequence_engine._rebuild_data_catalogs()  # noqa: SLF001

    def _ensure_connected(self) -> MotorControllerEngine:
        engine = self._engine()
        if engine.connected_driver is None:
            engine.connect_preferred_driver()
        return engine

    def _current_state(self):
        return self._engine().get_engine_state()

    def connect(self) -> None:
        """Ensure a motor controller is connected and start monitoring."""
        self._ensure_connected()
        self.start_monitoring()

    def configure(self) -> None:
        """No-op — the engine is configured by dedicated state-control plugins."""

    def disconnect(self) -> None:
        """Stop monitoring while leaving the shared engine running."""
        self.stop_monitoring()

    @property
    def quantity_names(self) -> list[str]:
        names = []
        if self.report_angle:
            names.append("angle")
        if self.report_target_angle:
            names.append("target_angle")
        if self.report_moving:
            names.append("moving")
        if self.report_angular_rate:
            names.append("angular_rate")
        if self.report_at_target:
            names.append("at_target")
        if self.report_stability:
            names.append("stable")
        return names

    @property
    def units(self) -> dict[str, str]:
        units = {}
        if self.report_angle:
            units["angle"] = "deg"
        if self.report_target_angle:
            units["target_angle"] = "deg"
        if self.report_moving:
            units["moving"] = ""
        if self.report_angular_rate:
            units["angular_rate"] = "deg/s"
        if self.report_at_target:
            units["at_target"] = ""
        if self.report_stability:
            units["stable"] = ""
        return units

    def read(self, *, force_poll: bool = False) -> dict[str, float]:
        if force_poll or self.force_fresh_poll:
            state = self._ensure_connected().read_controller_state() or self._current_state()
        else:
            state = self._current_state()

        reading = state.reading
        result: dict[str, float] = {}

        if self.report_angle:
            result["angle"] = math.nan if reading is None else float(reading.angle)
        if self.report_target_angle:
            result["target_angle"] = (
                math.nan if state.target_angle is None else float(state.target_angle)
            )
        if self.report_moving:
            result["moving"] = math.nan if reading is None else (1.0 if reading.moving else 0.0)
        if self.report_angular_rate:
            result["angular_rate"] = math.nan if reading is None else float(reading.angular_rate)
        if self.report_at_target:
            result["at_target"] = 1.0 if state.at_target else 0.0
        if self.report_stability:
            result["stable"] = 1.0 if state.stable else 0.0

        self._last_reading = result
        return result

    def angle(self) -> float:
        """Return the latest measured motor angle in degrees."""
        state = self._current_state()
        reading = state.reading
        return math.nan if reading is None else float(reading.angle)

    def target_angle(self) -> float:
        """Return the current target angle in degrees, if known."""
        state = self._current_state()
        return math.nan if state.target_angle is None else float(state.target_angle)

    def moving(self) -> float:
        """Return ``1.0`` while moving, ``0.0`` when idle, or NaN if unknown."""
        state = self._current_state()
        reading = state.reading
        return math.nan if reading is None else (1.0 if reading.moving else 0.0)

    def angular_rate(self) -> float:
        """Return the estimated angular rate in degrees per second."""
        state = self._current_state()
        reading = state.reading
        return math.nan if reading is None else float(reading.angular_rate)

    def at_target(self) -> float:
        """Return ``1.0`` when the engine reports at-target, else ``0.0``."""
        state = self._current_state()
        return 1.0 if state.at_target else 0.0

    def stable(self) -> float:
        """Return ``1.0`` when the engine reports stable, else ``0.0``."""
        state = self._current_state()
        return 1.0 if state.stable else 0.0

    def reported_values(self) -> dict[str, str]:
        var = self.instance_name
        values: dict[str, str] = {}

        if self.report_angle:
            values[f"{var}:Angle"] = f"{var}.angle()"
        if self.report_target_angle:
            values[f"{var}:Target Angle"] = f"{var}.target_angle()"
        if self.report_moving:
            values[f"{var}:Moving"] = f"{var}.moving()"
        if self.report_angular_rate:
            values[f"{var}:Angular Rate"] = f"{var}.angular_rate()"
        if self.report_at_target:
            values[f"{var}:At Target"] = f"{var}.at_target()"
        if self.report_stability:
            values[f"{var}:Stable"] = f"{var}.stable()"
        return values

    def to_json(self) -> dict[str, object]:
        data = super().to_json()
        data.update(
            {
                "report_angle": self.report_angle,
                "report_target_angle": self.report_target_angle,
                "report_moving": self.report_moving,
                "report_angular_rate": self.report_angular_rate,
                "report_at_target": self.report_at_target,
                "report_stability": self.report_stability,
                "force_fresh_poll": self.force_fresh_poll,
            }
        )
        return data

    def _restore_from_json(self, data: dict[str, object]) -> None:
        for key in (
            "report_angle",
            "report_target_angle",
            "report_moving",
            "report_angular_rate",
            "report_at_target",
            "report_stability",
            "force_fresh_poll",
        ):
            if key in data:
                setattr(self, key, bool(data[key]))
        self._refresh_catalogs()

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        return _MotorAngleMonitorSettingsWidget(self, parent=parent)


class _MotorAngleMonitorSettingsWidget(QWidget):
    """Configuration widget for :class:`MotorAngleMonitorPlugin`."""

    def __init__(
        self,
        plugin: MotorAngleMonitorPlugin,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plugin = plugin

        layout = QVBoxLayout(self)
        group = QGroupBox("Report parameters", self)
        form = QFormLayout(group)

        self._cb_angle = QCheckBox(group)
        self._cb_angle.setChecked(self._plugin.report_angle)
        self._cb_angle.toggled.connect(self._on_angle_toggled)
        form.addRow("Angle:", self._cb_angle)

        self._cb_target_angle = QCheckBox(group)
        self._cb_target_angle.setChecked(self._plugin.report_target_angle)
        self._cb_target_angle.toggled.connect(self._on_target_angle_toggled)
        form.addRow("Target angle:", self._cb_target_angle)

        self._cb_moving = QCheckBox(group)
        self._cb_moving.setChecked(self._plugin.report_moving)
        self._cb_moving.toggled.connect(self._on_moving_toggled)
        form.addRow("Moving:", self._cb_moving)

        self._cb_angular_rate = QCheckBox(group)
        self._cb_angular_rate.setChecked(self._plugin.report_angular_rate)
        self._cb_angular_rate.toggled.connect(self._on_angular_rate_toggled)
        form.addRow("Angular rate:", self._cb_angular_rate)

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

    def _on_angle_toggled(self, checked: bool) -> None:
        self._plugin.report_angle = checked
        self._plugin._refresh_catalogs()

    def _on_target_angle_toggled(self, checked: bool) -> None:
        self._plugin.report_target_angle = checked
        self._plugin._refresh_catalogs()

    def _on_moving_toggled(self, checked: bool) -> None:
        self._plugin.report_moving = checked
        self._plugin._refresh_catalogs()

    def _on_angular_rate_toggled(self, checked: bool) -> None:
        self._plugin.report_angular_rate = checked
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
