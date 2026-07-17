"""Shared support for temperature-controller state plugins."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import TYPE_CHECKING

from qtpy.QtWidgets import (
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.temperature_control.engine import TemperatureControllerEngine

if TYPE_CHECKING:
    from stoner_measurement.temperature_control.types import TemperatureEngineState

def _normalise_channels(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    channels: list[str] = []
    seen: set[str] = set()
    for value in values:
        channel = str(value).strip()
        if channel and channel not in seen:
            channels.append(channel)
            seen.add(channel)
    return None if not channels else channels


class TemperatureControllerPluginMixin:
    """Shared engine-backed behaviour for temperature state scan/sweep plugins."""

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"temperature"})

    def _init_temperature_controller_plugin(self) -> None:
        self.control_loop: int = 1
        self.ramp_rate: float = 1.0
        self.sensor_channels: list[str] | None = None

    def _state_control_loop(self, state: TemperatureEngineState | None = None) -> int:
        """Return a control loop usable for reading state from *state*.

        Prefer the configured :attr:`control_loop`, but fall back to any loop
        reported by the engine state so read-only helpers can still function
        with partial/mock state snapshots.
        """
        state = self._engine_state() if state is None else state
        if self.control_loop in state.input_channels or self.control_loop in state.setpoints:
            return self.control_loop
        return next(iter(state.input_channels or state.setpoints), self.control_loop)

    def _refresh_catalogs(self) -> None:
        if self.sequence_engine is not None:
            self.sequence_engine._rebuild_data_catalogs()  # noqa: SLF001

    def _engine(self) -> TemperatureControllerEngine:
        return TemperatureControllerEngine.instance()

    def _ensure_connected(self) -> TemperatureControllerEngine:
        engine = self._engine()
        if engine.connected_driver is None:
            engine.connect_preferred_driver()
        return engine

    def _engine_state(self, *, refresh: bool = False) -> TemperatureEngineState:
        engine = self._engine()
        state = engine.get_engine_state()
        if refresh and engine.connected_driver is not None:
            state = engine.read_controller_state() or state
        return state

    def _available_sensor_channels(self) -> list[str]:
        state = self._engine_state()
        if state.readings:
            return sorted(state.readings)
        driver = self._engine().connected_driver
        if driver is None:
            return []
        try:
            return list(driver.get_capabilities().input_channels)
        except Exception:
            return []

    @property
    def limits(self) -> tuple[float, float]:
        driver = self._engine().connected_driver
        if driver is None:
            return (float("-inf"), float("inf"))
        try:
            caps = driver.get_capabilities()
        except Exception:
            return (float("-inf"), float("inf"))
        low = float("-inf") if caps.min_temperature is None else float(caps.min_temperature)
        high = float("inf") if caps.max_temperature is None else float(caps.max_temperature)
        return (low, high)

    def connect(self) -> None:
        self._ensure_connected()
        self._engine_state(refresh=True)

    def configure(self) -> None:
        self._engine().set_ramp(self.control_loop, self.ramp_rate, True)

    def disconnect(self) -> None:
        """Leave the shared engine running."""

    def set_state(self, value: float) -> None:
        engine = self._ensure_connected()
        engine.set_ramp(self.control_loop, self.ramp_rate, True)
        engine.set_setpoint(self.control_loop, float(value))

    def set_target(self, value: float) -> None:
        engine = self._ensure_connected()
        engine.set_setpoint(self.control_loop, float(value))

    def set_rate(self, value: float) -> None:
        self.ramp_rate = max(0.0, float(value))
        engine = self._engine()
        if engine.connected_driver is not None:
            engine.set_ramp(self.control_loop, self.ramp_rate, True)

    def _control_channel(self, state: TemperatureEngineState | None = None) -> str | None:
        state = self._engine_state() if state is None else state
        loop = self._state_control_loop(state)
        channel = state.input_channels.get(loop)
        if channel:
            return channel
        settings = self._engine().get_loop_settings(loop)
        return None if settings is None or not settings.input_channel else settings.input_channel

    def get_state(self) -> float:
        state = self._engine_state()
        channel = self._control_channel(state)
        if channel and channel in state.readings:
            return float(state.readings[channel].value)
        if not state.readings:
            state = self._engine_state(refresh=True)
            channel = self._control_channel(state)
            if channel and channel in state.readings:
                return float(state.readings[channel].value)
        loop = self._state_control_loop(state)
        setpoint = state.setpoints.get(loop)
        if setpoint is not None:
            return float(setpoint)
        return float(getattr(self, "value", 0.0))

    def is_at_target(self) -> bool:
        state = self._engine_state(refresh=True)
        loop = self._state_control_loop(state)
        return bool(state.at_setpoint.get(loop, False))

    @property
    def control_setpoint(self) -> float:
        state = self._engine_state()
        loop = self._state_control_loop(state)
        setpoint = state.setpoints.get(loop)
        return math.nan if setpoint is None else float(setpoint)

    def sensor_value(self, channel: str) -> float:
        state = self._engine_state()
        reading = state.readings.get(channel)
        return math.nan if reading is None else float(reading.value)

    def reported_values(self) -> dict[str, str]:
        values = super().reported_values()
        selected = self._available_sensor_channels() if self.sensor_channels is None else list(self.sensor_channels)
        var = self.instance_name
        values[f"{var}:Loop Setpoint"] = f"{var}.control_setpoint"
        for channel in selected:
            values[f"{var}:Sensor {channel}"] = f"{var}.sensor_value({channel!r})"
        return values

    def _temperature_settings_to_json(self) -> dict[str, object]:
        return {
            "control_loop": self.control_loop,
            "ramp_rate": self.ramp_rate,
            "sensor_channels": None if self.sensor_channels is None else list(self.sensor_channels),
        }

    def _restore_temperature_settings(self, data: dict[str, object]) -> None:
        if "control_loop" in data:
            self.control_loop = max(1, int(data["control_loop"]))
        if "ramp_rate" in data:
            self.ramp_rate = max(0.0, float(data["ramp_rate"]))
        if "sensor_channels" in data:
            raw = data["sensor_channels"]
            self.sensor_channels = _normalise_channels(raw if isinstance(raw, list) else None)

    def _plugin_config_tabs(self) -> QWidget | None:
        return _TemperatureControllerSettingsWidget(self)


class _TemperatureControllerSettingsWidget(QWidget):
    """Configuration widget shared by temperature controller scan/sweep plugins."""

    def __init__(self, plugin: TemperatureControllerPluginMixin, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plugin = plugin
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()

        self._loop_spin = QSpinBox(self)
        self._loop_spin.setMinimum(1)
        self._loop_spin.setMaximum(99)
        self._loop_spin.setValue(self._plugin.control_loop)
        self._loop_spin.valueChanged.connect(self._on_loop_changed)
        form.addRow("Control loop:", self._loop_spin)

        self._sensor_edit = QLineEdit(
            "" if self._plugin.sensor_channels is None else ", ".join(self._plugin.sensor_channels), self
        )
        self._sensor_edit.setPlaceholderText("Comma-separated sensor channels; blank = all available")
        self._sensor_edit.editingFinished.connect(self._on_sensors_changed)
        form.addRow("Reported sensors:", self._sensor_edit)

        root.addLayout(form)
        root.addStretch(1)

    def _on_loop_changed(self, value: int) -> None:
        self._plugin.control_loop = max(1, int(value))
        self._plugin._refresh_catalogs()

    def _on_sensors_changed(self) -> None:
        text = self._sensor_edit.text().strip()
        values = None if not text else [part for part in text.split(",")]
        self._plugin.sensor_channels = _normalise_channels(values)
        self._plugin._refresh_catalogs()
