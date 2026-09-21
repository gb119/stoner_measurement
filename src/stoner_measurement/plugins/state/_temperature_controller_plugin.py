"""Shared support for temperature-controller state plugins."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import TYPE_CHECKING

from qtpy.QtWidgets import (
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.temperature_control.references import (
    ChannelRef,
    channel_ref,
    controller_id,
    reference_json,
)
from stoner_measurement.ui.temperature_selectors import (
    TemperatureLoopSelector,
    add_catalogue_picker,
    compact_reference,
    parse_selection,
    selection_text,
)
from stoner_measurement.ui.widgets import SISpinBox

if TYPE_CHECKING:
    from stoner_measurement.temperature_control.types import TemperatureEngineState

def _normalise_channels(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    channels: list[str] = []
    seen: set[str] = set()
    for value in values:
        channel = compact_reference(channel_ref(value)) if isinstance(value, (dict, ChannelRef)) else str(value).strip()
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
        self.controller_id = "primary"
        self.control_loop: int = 1
        self.ramp_rate: float = 1.0
        self.sensor_channels: list[str] | None = None
        publisher = getattr(TemperatureControllerEngine.instance(), "publisher", None)
        if publisher is not None:
            publisher.connection_changed.connect(self._refresh_catalogs)

    def _state_control_loop(self, state: TemperatureEngineState | None = None) -> int:
        """Return the configured loop without substituting a different target."""
        return self.control_loop

    def _refresh_catalogs(self) -> None:
        if self.sequence_engine is not None:
            self.sequence_engine._rebuild_data_catalogs()  # noqa: SLF001

    def _engine(self) -> TemperatureControllerEngine:
        engine = TemperatureControllerEngine.instance()
        return engine if self.controller_id == "primary" else engine.controller(self.controller_id)

    def _ensure_connected(self) -> TemperatureControllerEngine:
        service = TemperatureControllerEngine.instance()
        if hasattr(service, "ensure_controller"):
            service.ensure_controller(self.controller_id)
        engine = self._engine()
        if engine.connected_driver is None:
            engine.connect_preferred_driver()
        return engine

    def _engine_state(
        self,
        *,
        refresh: bool = False,
        max_age_seconds: float | None = None,
    ) -> TemperatureEngineState:
        engine = self._engine()
        state = engine.get_engine_state()
        stale = max_age_seconds is not None and engine.state_cache_age_seconds > max_age_seconds
        if (refresh or stale) and engine.connected_driver is not None:
            state = engine.read_controller_state() or engine.get_engine_state()
        return state

    def _available_sensor_channels(self):
        service = TemperatureControllerEngine.instance()
        if hasattr(service, "channel_catalogue"):
            return [compact_reference(item.reference) for item in service.channel_catalogue()]
        return sorted(self._engine_state().readings)

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
        state = self._engine_state(max_age_seconds=self.engine_cache_max_age_seconds)
        loop = self._state_control_loop(state)
        return bool(state.stable.get(loop, False))

    @property
    def control_setpoint(self) -> float:
        state = self._engine_state()
        loop = self._state_control_loop(state)
        setpoint = state.setpoints.get(loop)
        return math.nan if setpoint is None else float(setpoint)

    def sensor_value(self, channel: str) -> float:
        state = self._engine_state()
        ref = channel_ref(channel)
        state = TemperatureControllerEngine.instance().get_engine_state()
        local = state if ref.controller_id == "primary" else state.for_controller(ref.controller_id)
        reading = local.readings.get(ref.channel)
        return math.nan if reading is None else float(reading.value)

    def reported_values(self) -> dict[str, str]:
        values = super().reported_values()
        selected = self._available_sensor_channels() if self.sensor_channels is None else list(self.sensor_channels)
        var = self.instance_name
        values[f"{var}:Loop Setpoint"] = f"{var}.control_setpoint"
        if hasattr(self, "settle_timeout_minutes"):
            values[f"{var}:Timed Out"] = f"{var}.timed_out"
        for channel in selected:
            values[f"{var}:Sensor {channel}"] = f"{var}.sensor_value({reference_json(channel)!r})"
        return values

    def reported_value_units(self) -> dict[str, str]:
        """Return temperature units for the loop setpoint and sensor readings."""
        units = super().reported_value_units()
        selected = self._available_sensor_channels() if self.sensor_channels is None else list(self.sensor_channels)
        var = self.instance_name
        units[f"{var}:Loop Setpoint"] = self.units
        if hasattr(self, "settle_timeout_minutes"):
            units[f"{var}:Timed Out"] = ""
        units.update({f"{var}:Sensor {channel}": self.units for channel in selected})
        return units

    def _temperature_settings_to_json(self) -> dict[str, object]:
        return {
            "controller_id": self.controller_id,
            "control_loop": self.control_loop,
            "ramp_rate": self.ramp_rate,
            "sensor_channels": None if self.sensor_channels is None else [reference_json(ch) for ch in self.sensor_channels],
        }

    def _restore_temperature_settings(self, data: dict[str, object]) -> None:
        self.controller_id = controller_id(data.get("controller_id", "primary"))
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

        self._loop_selector = TemperatureLoopSelector(self._plugin, self)
        form.addRow("Control loop:", self._loop_selector)

        if hasattr(self._plugin, "settle_timeout_minutes"):
            self._settle_timeout_spin = SISpinBox(self, allow_expressions=True)
            self._settle_timeout_spin.setObjectName("temperature_settle_timeout_minutes")
            self._settle_timeout_spin.setOpts(
                bounds=(0.1, 1.0e6), decimals=3, step=1.0, suffix="min"
            )
            self._settle_timeout_spin.setValue(self._plugin.settle_timeout_minutes)
            self._settle_timeout_spin.setToolTip(
                "Maximum time to wait for the selected loop to satisfy the "
                "temperature stability criteria before the scan continues. "
                "Numbers are minutes; expressions are evaluated separately "
                "at each temperature point."
            )
            self._settle_timeout_spin.sigValueChanged.connect(
                lambda spin: setattr(
                    self._plugin, "settle_timeout_minutes", spin.value()
                )
            )
            form.addRow("Stability timeout:", self._settle_timeout_spin)

        self._sensor_edit = QLineEdit(
            "" if self._plugin.sensor_channels is None else ", ".join(selection_text(ch) for ch in self._plugin.sensor_channels), self
        )
        self._sensor_edit.setPlaceholderText("Comma-separated sensor channels; blank = all available")
        self._sensor_edit.editingFinished.connect(self._on_sensors_changed)
        form.addRow("Reported sensors:", self._sensor_edit)
        add_catalogue_picker(form, self._sensor_edit)

        root.addLayout(form)
        root.addStretch(1)

    def _on_loop_changed(self, value: int) -> None:
        self._plugin.control_loop = max(1, int(value))
        self._plugin._refresh_catalogs()

    def _on_sensors_changed(self) -> None:
        text = self._sensor_edit.text().strip()
        values = None if not text else parse_selection(text)
        self._plugin.sensor_channels = _normalise_channels(values)
        self._plugin._refresh_catalogs()
