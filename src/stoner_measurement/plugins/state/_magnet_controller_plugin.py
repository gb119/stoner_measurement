"""Shared support for magnet-controller state plugins."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import TYPE_CHECKING

from qtpy.QtWidgets import QCheckBox, QFormLayout, QHBoxLayout, QVBoxLayout, QWidget

from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.ui.widgets import SISpinBox

if TYPE_CHECKING:
    from stoner_measurement.magnet_control.types import MagnetEngineState

_OUTPUT_OPTIONS = ("field", "current", "voltage")


def _normalise_outputs(values: Iterable[str] | None) -> list[str] | None:
    """Normalise selected output names.

    Returns ``None`` when all supported outputs are selected so the plugin can
    preserve the existing "all outputs" sentinel used by state plugins.
    """
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


class MagnetControllerPluginMixin:
    """Shared engine-backed behaviour for magnet state scan/sweep plugins."""

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"magnetic_field"})

    def _init_magnet_controller_plugin(self) -> None:
        self.ramp_rate: float = 0.1
        self.use_plugin_ramp_rate: bool = True
        self.report_outputs: list[str] | None = None

    def _refresh_catalogs(self) -> None:
        if self.sequence_engine is not None:
            self.sequence_engine._rebuild_data_catalogs()  # noqa: SLF001

    def _engine(self) -> MagnetControllerEngine:
        return MagnetControllerEngine.instance()

    def _ensure_connected(self) -> MagnetControllerEngine:
        engine = self._engine()
        if engine.connected_driver is None:
            engine.connect_preferred_driver()
        return engine

    def _engine_state(self, *, refresh: bool = False) -> MagnetEngineState:
        engine = self._engine()
        state = engine.get_engine_state()
        if refresh and engine.connected_driver is not None:
            state = engine.read_controller_state() or state
        return state

    def _magnet_limits(self) -> tuple[float, float]:
        self._raise_if_quenched(self._engine_state())
        limits = self._engine().get_limits()
        max_field = None if limits is None else limits.max_field
        return (float("-inf"), float("inf") if max_field is None else float(max_field))

    def _raise_if_quenched(self, state: MagnetEngineState) -> None:
        """Raise to stop scripts when the magnet controller reports a quench."""
        if state.reading is not None and state.reading.quench_detected:
            raise RuntimeError("Magnet controller reported a quench condition.")

    @property
    def limits(self) -> tuple[float, float]:
        return self._magnet_limits()

    def connect(self) -> None:
        self._ensure_connected()
        self._raise_if_quenched(self._engine_state(refresh=True))

    def configure(self) -> None:
        self._raise_if_quenched(self._engine_state())
        if self.use_plugin_ramp_rate:
            self._engine().set_ramp_rate_field(self.ramp_rate)

    def disconnect(self) -> None:
        """Leave the shared engine running."""

    def set_state(self, value: float) -> None:
        engine = self._ensure_connected()
        self._raise_if_quenched(self._engine_state(refresh=True))
        if self.use_plugin_ramp_rate:
            engine.set_ramp_rate_field(self.ramp_rate)
        engine.ramp_to_field(float(value))

    def set_target(self, value: float) -> None:
        engine = self._ensure_connected()
        self._raise_if_quenched(self._engine_state(refresh=True))
        engine.set_target_field(float(value))
        engine.ramp_to_target()

    def set_rate(self, value: float) -> None:
        self.ramp_rate = max(0.0, float(value))
        if not self.use_plugin_ramp_rate:
            return
        self._raise_if_quenched(self._engine_state())
        engine = self._engine()
        if engine.connected_driver is not None:
            engine.set_ramp_rate_field(self.ramp_rate)

    def get_state(self) -> float:
        state = self._engine_state()
        if state.reading is None:
            state = self._engine_state(refresh=True)
        self._raise_if_quenched(state)
        if state.reading is not None and state.reading.field is not None:
            return float(state.reading.field)
        if state.target_field is not None:
            return float(state.target_field)
        return float(getattr(self, "value", 0.0))

    def is_at_target(self) -> bool:
        state = self._engine_state(refresh=True)
        self._raise_if_quenched(state)
        return bool(state.at_target)

    @property
    def field(self) -> float:
        state = self._engine_state()
        self._raise_if_quenched(state)
        if state.reading is None or state.reading.field is None:
            return math.nan
        return float(state.reading.field)

    @property
    def current(self) -> float:
        state = self._engine_state()
        self._raise_if_quenched(state)
        if state.reading is None:
            return math.nan
        return float(state.reading.current)

    @property
    def voltage(self) -> float:
        state = self._engine_state()
        self._raise_if_quenched(state)
        if state.reading is None or state.reading.voltage is None:
            return math.nan
        return float(state.reading.voltage)

    def reported_values(self) -> dict[str, str]:
        values = super().reported_values()
        selected = _OUTPUT_OPTIONS if self.report_outputs is None else tuple(self.report_outputs)
        var = self.instance_name
        if "field" in selected:
            values[f"{var}:Field"] = f"{var}.field"
        if "current" in selected:
            values[f"{var}:Current"] = f"{var}.current"
        if "voltage" in selected:
            values[f"{var}:Voltage"] = f"{var}.voltage"
        return values

    def _magnet_settings_to_json(self) -> dict[str, object]:
        return {
            "ramp_rate": self.ramp_rate,
            "report_outputs": None if self.report_outputs is None else list(self.report_outputs),
        }

    def _restore_magnet_settings(self, data: dict[str, object]) -> None:
        if "ramp_rate" in data:
            self.ramp_rate = max(0.0, float(data["ramp_rate"]))
        if "report_outputs" in data:
            raw = data["report_outputs"]
            self.report_outputs = _normalise_outputs(raw if isinstance(raw, list) else None)

    def _plugin_config_tabs(self) -> QWidget | None:
        return _MagnetControllerSettingsWidget(self)


class _MagnetControllerSettingsWidget(QWidget):
    """Configuration widget shared by magnet controller scan/sweep plugins."""

    def __init__(self, plugin: MagnetControllerPluginMixin, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plugin = plugin
        self._output_checks: dict[str, QCheckBox] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()

        self._ramp_rate_spin = SISpinBox()
        outputs_row = QHBoxLayout()
        selected = set(_OUTPUT_OPTIONS if self._plugin.report_outputs is None else self._plugin.report_outputs)
        for name in _OUTPUT_OPTIONS:
            check = QCheckBox(name.title(), self)
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
