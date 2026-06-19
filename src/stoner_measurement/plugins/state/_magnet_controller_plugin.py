"""Shared support for magnet-controller state plugins."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import TYPE_CHECKING

from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.magnet_controller import MagnetController
from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.ui.widgets import SISpinBox

if TYPE_CHECKING:
    from stoner_measurement.magnet_control.types import MagnetEngineState

_TRANSPORT_OPTIONS = ("Serial", "GPIB", "Ethernet", "Null (test)")
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

    def _init_magnet_controller_plugin(self) -> None:
        self.driver_name: str = self._available_driver_names()[0] if self._available_driver_names() else ""
        self.transport_name: str = "Null (test)"
        self.address: str = ""
        self.ramp_rate: float = 0.1
        self.report_outputs: list[str] | None = None

    @staticmethod
    def _available_driver_names() -> list[str]:
        manager = InstrumentDriverManager()
        manager.discover()
        return sorted(manager.drivers_by_type(MagnetController))

    def _refresh_catalogs(self) -> None:
        if self.sequence_engine is not None:
            self.sequence_engine._rebuild_data_catalogs()  # noqa: SLF001

    def _engine(self) -> MagnetControllerEngine:
        return MagnetControllerEngine.instance()

    def _ensure_connected(self) -> MagnetControllerEngine:
        engine = self._engine()
        connected_driver = engine.connected_driver
        current_name = type(connected_driver).__name__ if connected_driver is not None else ""
        active_driver_name = getattr(engine, "connected_driver_name", current_name)
        active_transport = getattr(engine, "connected_transport_name", None)
        active_address = getattr(engine, "connected_address", None)
        desired_driver_name = self.driver_name.strip()
        desired_transport = self.transport_name.strip()
        desired_address = self.address.strip()
        needs_connect = (
            connected_driver is None
            or (desired_driver_name and active_driver_name != desired_driver_name)
            or (active_transport is not None and active_transport != desired_transport)
            or (active_address is not None and active_address != desired_address)
        )
        if needs_connect:
            if not self.driver_name:
                raise RuntimeError("No magnet controller driver selected.")
            engine.connect_driver(desired_driver_name, desired_transport, desired_address)
        return engine

    def _engine_state(self, *, refresh: bool = False) -> MagnetEngineState:
        engine = self._engine()
        state = engine.get_engine_state()
        if refresh and engine.connected_driver is not None:
            state = engine.read_controller_state() or state
        return state

    def _magnet_limits(self) -> tuple[float, float]:
        limits = self._engine().get_limits()
        max_field = None if limits is None else limits.max_field
        return (float("-inf"), float("inf") if max_field is None else float(max_field))

    @property
    def limits(self) -> tuple[float, float]:
        return self._magnet_limits()

    def connect(self) -> None:
        self._ensure_connected()
        self._engine_state(refresh=True)

    def configure(self) -> None:
        self._engine().set_ramp_rate_field(self.ramp_rate)

    def disconnect(self) -> None:
        """Leave the shared engine running."""

    def set_state(self, value: float) -> None:
        engine = self._ensure_connected()
        engine.set_ramp_rate_field(self.ramp_rate)
        engine.ramp_to_field(float(value))

    def set_target(self, value: float) -> None:
        engine = self._ensure_connected()
        engine.set_target_field(float(value))
        engine.ramp_to_target()

    def set_rate(self, value: float) -> None:
        self.ramp_rate = max(0.0, float(value)) * 60.0
        engine = self._engine()
        if engine.connected_driver is not None:
            engine.set_ramp_rate_field(self.ramp_rate)

    def get_state(self) -> float:
        state = self._engine_state()
        if state.reading is None:
            state = self._engine_state(refresh=True)
        if state.reading is not None and state.reading.field is not None:
            return float(state.reading.field)
        if state.target_field is not None:
            return float(state.target_field)
        return float(getattr(self, "value", 0.0))

    def is_at_target(self) -> bool:
        state = self._engine_state()
        return bool(state.reading is not None and state.reading.at_target)

    @property
    def field(self) -> float:
        state = self._engine_state()
        if state.reading is None or state.reading.field is None:
            return math.nan
        return float(state.reading.field)

    @property
    def current(self) -> float:
        state = self._engine_state()
        if state.reading is None:
            return math.nan
        return float(state.reading.current)

    @property
    def voltage(self) -> float:
        state = self._engine_state()
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
            "driver_name": self.driver_name,
            "transport_name": self.transport_name,
            "address": self.address,
            "ramp_rate": self.ramp_rate,
            "report_outputs": None if self.report_outputs is None else list(self.report_outputs),
        }

    def _restore_magnet_settings(self, data: dict[str, object]) -> None:
        if "driver_name" in data:
            self.driver_name = str(data["driver_name"])
        if "transport_name" in data:
            transport = str(data["transport_name"])
            self.transport_name = transport if transport in _TRANSPORT_OPTIONS else "Null (test)"
        if "address" in data:
            self.address = str(data["address"])
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

        self._driver_combo = QComboBox(self)
        self._driver_combo.setEditable(True)
        self._driver_combo.addItems(self._plugin._available_driver_names())
        self._driver_combo.setCurrentText(self._plugin.driver_name)
        self._driver_combo.currentTextChanged.connect(self._on_driver_changed)
        form.addRow("Driver:", self._driver_combo)

        self._transport_combo = QComboBox(self)
        self._transport_combo.addItems(_TRANSPORT_OPTIONS)
        self._transport_combo.setCurrentText(self._plugin.transport_name)
        self._transport_combo.currentTextChanged.connect(self._on_transport_changed)
        form.addRow("Transport:", self._transport_combo)

        self._address_edit = QLineEdit(self._plugin.address, self)
        self._address_edit.setPlaceholderText("port=/dev/ttyUSB0;baud=9600, GPIB0::2::INSTR, or host:port")
        self._address_edit.editingFinished.connect(self._on_address_changed)
        form.addRow("Address:", self._address_edit)

        self._ramp_rate_spin = SISpinBox()
        self._ramp_rate_spin.setOpts(bounds=(0.0, 1e9), decimals=6, suffix="T/min")
        self._ramp_rate_spin.setValue(self._plugin.ramp_rate)
        self._ramp_rate_spin.sigValueChanged.connect(self._on_ramp_rate_changed)
        form.addRow("Ramp rate:", self._ramp_rate_spin)

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

    def _on_driver_changed(self, value: str) -> None:
        self._plugin.driver_name = value.strip()

    def _on_transport_changed(self, value: str) -> None:
        self._plugin.transport_name = value

    def _on_address_changed(self) -> None:
        self._plugin.address = self._address_edit.text().strip()

    def _on_ramp_rate_changed(self, spinbox: SISpinBox) -> None:
        self._plugin.ramp_rate = max(0.0, float(spinbox.value()))

    def _on_outputs_changed(self) -> None:
        selected = [name for name, check in self._output_checks.items() if check.isChecked()]
        self._plugin.report_outputs = _normalise_outputs(selected)
        self._plugin._refresh_catalogs()
