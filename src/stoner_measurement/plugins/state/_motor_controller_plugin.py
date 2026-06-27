"""Shared support for motor-controller state plugins."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import TYPE_CHECKING

from qtpy.QtWidgets import QCheckBox, QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from stoner_measurement.motor_control.engine import MotorControllerEngine
from stoner_measurement.ui.widgets import SISpinBox

if TYPE_CHECKING:
    from stoner_measurement.motor_control.types import MotorEngineState

_OUTPUT_OPTIONS = ("angle", "target_angle", "angular_rate")


def _normalise_outputs(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = str(value).strip().lower()
        if key in _OUTPUT_OPTIONS and key not in seen:
            selected.append(key)
            seen.add(key)
    return None if len(selected) == len(_OUTPUT_OPTIONS) else selected


class MotorControllerPluginMixin:
    """Shared engine-backed behaviour for motor state scan/sweep plugins."""

    def _init_motor_controller_plugin(self) -> None:
        self.velocity: float = 10.0
        self.acceleration: float = 10.0
        self.report_outputs: list[str] | None = None

    def _refresh_catalogs(self) -> None:
        if self.sequence_engine is not None:
            self.sequence_engine._rebuild_data_catalogs()  # noqa: SLF001

    def _engine(self) -> MotorControllerEngine:
        return MotorControllerEngine.instance()

    def _ensure_connected(self) -> MotorControllerEngine:
        engine = self._engine()
        if engine.connected_driver is None:
            raise RuntimeError("No motor controller is connected.")
        return engine

    def _engine_state(self, *, refresh: bool = False) -> MotorEngineState:
        engine = self._engine()
        state = engine.get_engine_state()
        if refresh and engine.connected_driver is not None:
            state = engine.read_controller_state() or state
        return state

    @property
    def limits(self) -> tuple[float, float]:
        """Return the nominal scan limits exposed by this plugin."""
        return (float("-inf"), float("inf"))

    def connect(self) -> None:
        """Ensure that a shared motor-controller engine is available."""
        self._ensure_connected()

    def configure(self) -> None:
        """Push the configured velocity and acceleration into the engine."""
        engine = self._ensure_connected()
        engine.set_velocity(self.velocity)
        engine.set_acceleration(self.acceleration)

    def disconnect(self) -> None:
        """Leave the shared engine running."""

    def set_state(self, value: float) -> None:
        """Move the controller to the requested absolute angular set-point."""
        engine = self._ensure_connected()
        engine.set_velocity(self.velocity)
        engine.set_acceleration(self.acceleration)
        engine.move_to_angle(float(value))

    def set_target(self, value: float) -> None:
        """Compatibility alias that forwards to :meth:`set_state`."""
        self.set_state(value)

    def set_rate(self, value: float) -> None:
        """Update the motion velocity used for subsequent movements."""
        self.velocity = max(0.0, float(value))
        engine = self._engine()
        if engine.connected_driver is not None:
            engine.set_velocity(self.velocity)

    def get_state(self) -> float:
        """Return the best current estimate of the motor angle in degrees."""
        state = self._engine_state()
        if state.reading is None:
            state = self._engine_state(refresh=True)
        if state.reading is not None:
            return float(state.reading.angle)
        if state.target_angle is not None:
            return float(state.target_angle)
        return float(getattr(self, "value", 0.0))

    def is_at_target(self) -> bool:
        """Return ``True`` when the engine reports the motor at its target."""
        state = self._engine_state(refresh=True)
        return bool(state.at_target)

    @property
    def angle(self) -> float:
        """Return the latest measured motor angle in degrees."""
        state = self._engine_state()
        if state.reading is None:
            return math.nan
        return float(state.reading.angle)

    @property
    def target_angle(self) -> float:
        """Return the current target angle in degrees, if known."""
        state = self._engine_state()
        if state.target_angle is None:
            return math.nan
        return float(state.target_angle)

    @property
    def angular_rate(self) -> float:
        """Return the estimated angular rate in degrees per second."""
        state = self._engine_state()
        if state.reading is None:
            return math.nan
        return float(state.reading.angular_rate)

    def reported_values(self) -> dict[str, str]:
        """Return value-catalogue expressions exposed by this plugin."""
        values = super().reported_values()
        selected = _OUTPUT_OPTIONS if self.report_outputs is None else tuple(self.report_outputs)
        var = self.instance_name
        if "angle" in selected:
            values[f"{var}:Angle"] = f"{var}.angle"
        if "target_angle" in selected:
            values[f"{var}:Target Angle"] = f"{var}.target_angle"
        if "angular_rate" in selected:
            values[f"{var}:Angular Rate"] = f"{var}.angular_rate"
        return values

    def _motor_settings_to_json(self) -> dict[str, object]:
        return {
            "velocity": self.velocity,
            "acceleration": self.acceleration,
            "report_outputs": None if self.report_outputs is None else list(self.report_outputs),
        }

    def _restore_motor_settings(self, data: dict[str, object]) -> None:
        if "velocity" in data:
            self.velocity = max(0.0, float(data["velocity"]))
        if "acceleration" in data:
            self.acceleration = max(0.0, float(data["acceleration"]))
        if "report_outputs" in data:
            raw = data["report_outputs"]
            self.report_outputs = _normalise_outputs(raw if isinstance(raw, list) else None)

    def _plugin_config_tabs(self) -> QWidget | None:
        return _MotorControllerSettingsWidget(self)


class _MotorControllerSettingsWidget(QWidget):
    """Configuration widget shared by motor controller scan/sweep plugins."""

    def __init__(self, plugin: MotorControllerPluginMixin, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plugin = plugin
        self._output_checks: dict[str, QCheckBox] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()

        self._velocity_spin = SISpinBox()
        self._velocity_spin.setOpts(bounds=(0.001, 10000.0), decimals=3, suffix="°/s", step=1.0)
        self._velocity_spin.setValue(self._plugin.velocity)
        self._velocity_spin.sigValueChanged.connect(
            lambda sb: setattr(self._plugin, "velocity", max(0.0, float(sb.value())))
        )
        form.addRow("Velocity:", self._velocity_spin)

        self._acceleration_spin = SISpinBox()
        self._acceleration_spin.setOpts(bounds=(0.001, 10000.0), decimals=3, suffix="°/s²", step=1.0)
        self._acceleration_spin.setValue(self._plugin.acceleration)
        self._acceleration_spin.sigValueChanged.connect(
            lambda sb: setattr(self._plugin, "acceleration", max(0.0, float(sb.value())))
        )
        form.addRow("Acceleration:", self._acceleration_spin)

        outputs_row = QHBoxLayout()
        selected = set(_OUTPUT_OPTIONS if self._plugin.report_outputs is None else self._plugin.report_outputs)
        for name in _OUTPUT_OPTIONS:
            check = QCheckBox(name.replace("_", " ").title(), self)
            check.setChecked(name in selected)
            check.stateChanged.connect(self._on_outputs_changed)
            self._output_checks[name] = check
            outputs_row.addWidget(check)
        outputs_row.addStretch(1)
        outputs_widget = QWidget(self)
        outputs_widget.setLayout(outputs_row)
        form.addRow("Reported outputs:", outputs_widget)

        root.addLayout(form)
        root.addStretch(1)

    def _on_outputs_changed(self) -> None:
        selected = [name for name, check in self._output_checks.items() if check.isChecked()]
        self._plugin.report_outputs = _normalise_outputs(selected)
        self._plugin._refresh_catalogs()
