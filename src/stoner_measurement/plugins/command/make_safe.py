"""Command plugin for returning shared hardware controllers to safe states."""

from __future__ import annotations

import time
from typing import Any

from qtpy.QtWidgets import QCheckBox, QFormLayout, QLabel, QWidget

from stoner_measurement.instruments.motor_controller import MotorMoveDirection
from stoner_measurement.instruments.temperature_controller import ControlMode
from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.motor_control.engine import MotorControllerEngine
from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine


class MakeSafeCommand(CommandPlugin):
    """Make the selected temperature, magnet, and motor systems safe."""

    _MAGNET_POLL_INTERVAL_SECONDS = 0.5
    _MAGNET_TIMEOUT_SECONDS = 300.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.temperature = True
        self.magnet = True
        self.motor = True
        self.always_make_safe = False

    @property
    def name(self) -> str:
        return "Make Safe"

    @property
    def controller_features(self) -> frozenset[str]:
        features = set()
        if self.temperature:
            features.add("temperature")
        if self.magnet:
            features.add("magnet")
        if self.motor:
            features.add("motor")
        return frozenset(features)

    def execute(self) -> None:
        if self.temperature:
            self._make_temperature_safe()
        if self.magnet:
            self._make_magnet_safe()
        if self.motor:
            MotorControllerEngine.instance().move_home(MotorMoveDirection.SHORTEST)

    @staticmethod
    def _make_temperature_safe() -> None:
        engine = TemperatureControllerEngine.instance()
        driver = engine.connected_driver
        if driver is None:
            return
        capabilities = driver.get_capabilities()
        for loop in range(1, capabilities.num_loops + 1):
            engine.set_manual_heater_output(loop, 0.0)
            engine.set_heater_range(loop, 0)
        if capabilities.has_gas_auto_mode:
            engine.set_gas_auto(False)
        if capabilities.has_cryogen_control:
            engine.set_needle_valve(0.0)
        for loop in range(1, capabilities.num_loops + 1):
            engine.set_loop_mode(loop, ControlMode.OFF)

    def _make_magnet_safe(self) -> None:
        engine = MagnetControllerEngine.instance()
        if engine.connected_driver is None:
            return
        engine.go_to_zero()
        deadline = time.monotonic() + self._MAGNET_TIMEOUT_SECONDS
        while True:
            state = engine.read_controller_state()
            if state is not None and state.at_target:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for the magnet to ramp to zero.")
            time.sleep(self._MAGNET_POLL_INTERVAL_SECONDS)
        engine.heater_off()

    def generate_finally_code(self, indent: int) -> list[str]:
        if not self.always_make_safe:
            return []
        return [f"{'    ' * indent}{self.instance_name}()"]

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        for label, attribute in (
            ("Temperature", "temperature"),
            ("Magnet", "magnet"),
            ("Motor", "motor"),
            ("Always make safe", "always_make_safe"),
        ):
            check = QCheckBox(widget)
            check.setChecked(bool(getattr(self, attribute)))
            check.toggled.connect(lambda checked, attr=attribute: setattr(self, attr, checked))
            layout.addRow(f"{label}:", check)
        layout.addRow(
            QLabel(
                "<i>Always make safe also runs this command at the start of the generated script's finally block.</i>",
                widget,
            )
        )
        return widget

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data.update(
            temperature=self.temperature,
            magnet=self.magnet,
            motor=self.motor,
            always_make_safe=self.always_make_safe,
        )
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        for attribute in ("temperature", "magnet", "motor", "always_make_safe"):
            if attribute in data:
                setattr(self, attribute, bool(data[attribute]))
