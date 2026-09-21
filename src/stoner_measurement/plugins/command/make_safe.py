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
    """Make the selected temperature, magnet, and motor systems safe.

    Use this command to perform the application's defined shutdown actions
    at a chosen sequence position. On **General**, select **Temperature**,
    **Magnet**, and/or **Motor**; all three are selected initially. Enable
    **Always make safe** to also execute these actions at the start of the
    generated script's finally block, including when the sequence fails.

    For a connected temperature controller, heater outputs and ranges are set
    to zero and control loops switched off. Supported gas-auto and needle-valve
    controls are disabled or closed. A connected magnet is ramped to zero,
    with a five-minute wait for the target, before its heater is switched off.
    The motor is sent home using the shortest route. Temperature and magnet
    actions are skipped if their controllers are disconnected.

    Actions run in temperature, magnet, then motor order. A failure propagates
    and prevents later actions in this call; this is not a guarantee that every
    system has reached a safe state. The command publishes no scalar outputs.

    Attributes:
        temperature (bool):
            Switch off temperature control; defaults to True.
        magnet (bool):
            Ramp to zero and switch off the magnet heater; defaults to True.
        motor (bool):
            Send the motor home; defaults to True.
        always_make_safe (bool):
            Also run during generated sequence cleanup; defaults to False.
        instance_name (str):
            Inherited Python identifier for this instance in the Script tab and
            QtConsole.
        comment (str):
            Inherited optional note displayed beside this step.
        sequence_engine (SequenceEngine | None):
            Inherited owning engine and its live namespace; None while
            detached.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        With an instance named ``make_safe`` in the sequence, use the
        QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            make_safe.temperature = True
            make_safe.magnet = True
            make_safe.motor = False
            make_safe.always_make_safe = True
    """

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
        sessions = getattr(engine, "controllers", {"primary": engine})
        failures = []
        for slot, session in sessions.items():
            if session.connected_driver is None:
                continue
            try:
                caps = session.connected_driver.get_capabilities()
                loops = getattr(caps, "loop_numbers", tuple(range(1, caps.num_loops + 1)))
                actions = []
                for loop in loops:
                    if getattr(caps, "has_manual_heater_output", True):
                        actions.append((session.set_manual_heater_output, (loop, 0.0)))
                    actions.append((session.set_heater_range, (loop, 0)))
                if caps.has_gas_auto_mode:
                    actions.append((session.set_gas_auto, (False,)))
                if caps.has_cryogen_control:
                    actions.append((session.set_needle_valve, (0.0,)))
                actions.extend((session.set_loop_mode, (loop, ControlMode.OFF)) for loop in loops)
                for action, args in actions:
                    try:
                        action(*args)
                    except Exception as error:
                        error.add_note(f"Temperature controller: {slot}; operation: {action.__name__}")
                        failures.append(error)
            except Exception as error:
                failures.append(error)
        if failures:
            raise ExceptionGroup("Could not make every temperature controller safe", failures)

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
