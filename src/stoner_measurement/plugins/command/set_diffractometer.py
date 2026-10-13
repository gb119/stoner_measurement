"""Command plugin for setting an X-ray diffractometer angle."""

from __future__ import annotations

import math
from typing import Any

from qtpy.QtWidgets import QFormLayout, QWidget

from stoner_measurement.plugins.command.set_engine_state import SetEngineStateCommand
from stoner_measurement.plugins.state._xray_diffractometer_plugin import (
    add_xray_motion_mode_row,
    normalise_xray_motion_mode,
)
from stoner_measurement.xray_control import XrayControllerEngine, XrayMotionMode


class SetDiffractometerCommand(SetEngineStateCommand):
    """Set an X-ray diffractometer angle during a sequence.

    Use this command for a single theta/omega, coupled theta-2theta, or
    detector/2theta move. The **Axes** control selects the motion relationship;
    the **Setpoint expression** is an expression-capable SI spin box in degrees.
    Motion uses the speed and coupled datum offset already configured in the
    X-ray engine. The preferred instrument is reconnected automatically when
    required. The inherited **Wait expression** controls whether the command
    waits for completion. With ``False``, the move runs in the background and
    outputs describe the latest known position with At Target false while
    motion is pending. Eventual failures are reported by the engine and retained
    in :attr:`operation`; waiting commands propagate failures to the sequence.

    Final theta, 2-theta, detector counts, and at-target state are published as
    scalar outputs.

    Attributes:
        axes (XrayMotionMode):
            Motion relationship; defaults to COUPLED.
        setpoint_expr (str):
            Target angle expression in degrees; coupled motion uses detector
            2-theta.
        wait_expr (str):
            Whether to wait for the target; defaults to "True".
        operation (XrayOperation | None):
            Read-only ticket for the latest background move. Once ``done`` is
            set, ``result()`` returns the completed state or raises its error.
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
        With an instance named ``set_diffractometer`` in the sequence, use the
        QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            from stoner_measurement.xray_control import XrayMotionMode
            set_diffractometer.axes = XrayMotionMode.COUPLED
            set_diffractometer.setpoint_expr = "scan_centre + 2.5"
    """

    setpoint_suffix = "°"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.axes = XrayMotionMode.COUPLED
        self._operation = None

    def execute(self) -> None:
        """Start a tracked move and preserve failure/cancellation on waiting runs."""
        self._operation = None
        try:
            super().execute()
        except BaseException:
            if self._operation is not None and not self._operation.done.is_set():
                self._ensure_engine().cancel_operation()
            raise
        if self._stop_requested() and self._operation is not None:
            self._ensure_engine().cancel_operation()

    @property
    def operation(self):
        """Latest background ticket; inspect ``done`` and call ``result()`` after completion."""
        return self._operation

    @property
    def name(self) -> str:
        return "Set Diffractometer"

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"xray"})

    @property
    def output_names(self) -> tuple[str, ...]:
        return ("Theta", "2-Theta", "Counts", "At Target")

    def _ensure_engine(self) -> XrayControllerEngine:
        engine = XrayControllerEngine.instance()
        if engine.connected_driver is None:
            engine.connect_preferred_driver()
        if engine.connected_driver is None:
            raise RuntimeError("No X-ray diffractometer is connected.")
        return engine

    def _set_target(self, engine: XrayControllerEngine, setpoint: float) -> None:
        start_move = getattr(engine, "start_move", None)
        if start_move is None:
            engine.move_to(setpoint, self.axes)
        else:
            self._operation = start_move(setpoint, self.axes)

    def _read_state(self, engine: XrayControllerEngine):
        if self._operation is not None:
            if self._operation.done.is_set():
                return self._operation.result()
            return engine.get_engine_state()
        return engine.read_controller_state() or engine.get_engine_state()

    def _target_reached(self, state, setpoint: float) -> bool:
        del setpoint
        if self._operation is not None:
            if not self._operation.done.is_set():
                return False
            state = self._operation.result()
        return bool(state.at_target and not state.moving)

    def _state_values(self, state) -> dict[str, float]:
        if self._operation is not None and self._operation.done.is_set():
            state = self._operation.result()
        snapshot = state.snapshot
        return {
            "Theta": math.nan if snapshot is None else float(snapshot.theta_deg),
            "2-Theta": math.nan if snapshot is None else float(snapshot.two_theta_deg),
            "Counts": math.nan if snapshot is None else float(snapshot.counts),
            "At Target": float(bool(state.at_target)),
        }

    def _add_specific_config(self, layout: QFormLayout, widget: QWidget) -> None:
        add_xray_motion_mode_row(layout, self, widget)

    def _specific_to_json(self) -> dict[str, Any]:
        return {"axes": self.axes.value}

    def _restore_specific_json(self, data: dict[str, Any]) -> None:
        self.axes = normalise_xray_motion_mode(data.get("axes", XrayMotionMode.COUPLED.value))
