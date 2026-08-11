"""Command plugin for setting a mass-flow-controller target."""

from __future__ import annotations

import math
from typing import Any

from qtpy.QtWidgets import QFormLayout, QWidget

from stoner_measurement.plugins.command.set_engine_state import SetEngineStateCommand
from stoner_measurement.pressure_control.engine import PressureControllerEngine
from stoner_measurement.ui.widgets import SISpinBox


class PressureSetFlowCommand(SetEngineStateCommand):
    """Set one MFC channel and optionally wait for actual flow to reach its target."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.channel_expr = "1"
        self._execution_channel = 1
        self.setpoint_expr = "0.0"
        self.tolerance_expr = "0.01"

    @property
    def name(self) -> str:
        return "Set Flow"

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"pressure"})

    @property
    def output_names(self) -> tuple[str, ...]:
        return ("Flow", "Flow Setpoint", "At Target")

    @property
    def channel(self) -> int:
        """Return the configured fixed channel when it is a numeric expression."""
        return int(self.channel_expr)

    @channel.setter
    def channel(self, value: int) -> None:
        self.channel_expr = str(max(1, int(value)))

    @property
    def flow_expr(self) -> str:
        """Compatibility alias for saved sequences using ``flow_expr``."""
        return self.setpoint_expr

    @flow_expr.setter
    def flow_expr(self, value: str) -> None:
        self.setpoint_expr = str(value)

    def _ensure_engine(self):
        engine = PressureControllerEngine.instance()
        if engine.connected_mfc_driver is None:
            engine.connect_preferred_mfc_driver()
        if engine.connected_mfc_driver is None:
            raise RuntimeError("No mass flow controller is connected.")
        return engine

    def _set_target(self, engine, setpoint: float) -> None:
        self._execution_channel = max(1, int(self.eval(self.channel_expr)))
        engine.set_flow_rate(self._execution_channel, setpoint)

    def _read_state(self, engine):
        return engine.read_controller_state() or engine.get_engine_state()

    def _target_reached(self, state, setpoint: float) -> bool:
        actual = state.flow_actual.get(self._execution_channel)
        if actual is None:
            return False
        tolerance = max(0.0, self.eval_float(self.tolerance_expr))
        return math.isclose(float(actual), setpoint, rel_tol=0.0, abs_tol=tolerance)

    def _state_values(self, state) -> dict[str, float]:
        actual = float(state.flow_actual.get(self._execution_channel, math.nan))
        target = float(state.flow_setpoints.get(self._execution_channel, math.nan))
        tolerance = max(0.0, self.eval_float(self.tolerance_expr))
        reached = math.isfinite(actual) and math.isclose(
            actual, target, rel_tol=0.0, abs_tol=tolerance
        )
        return {"Flow": actual, "Flow Setpoint": target, "At Target": float(reached)}

    def _add_specific_config(self, layout: QFormLayout, widget: QWidget) -> None:
        channel = SISpinBox(widget, value=self.channel_expr, allow_expressions=True)
        channel.setObjectName("mfc_channel_expression")
        channel.setOpts(bounds=(1, 99), decimals=0)
        channel.editingFinished.connect(
            lambda: setattr(self, "channel_expr", str(channel.value()))
        )
        layout.addRow("MFC channel expression:", channel)

        tolerance = SISpinBox(widget, value=self.tolerance_expr, siPrefix=True, allow_expressions=True)
        tolerance.setObjectName("flow_tolerance_expression")
        tolerance.setOpts(bounds=(0.0, None))
        tolerance.editingFinished.connect(
            lambda: setattr(self, "tolerance_expr", str(tolerance.value()))
        )
        layout.addRow("Flow tolerance expression:", tolerance)

    def _specific_to_json(self) -> dict[str, Any]:
        return {"channel_expr": self.channel_expr, "tolerance_expr": self.tolerance_expr}

    def _restore_specific_json(self, data: dict[str, Any]) -> None:
        raw_channel = data.get("channel_expr", data.get("channel", 1))
        self.channel_expr = str(raw_channel)
        self.tolerance_expr = str(data.get("tolerance_expr", "0.01"))
        if "setpoint_expr" not in data and "flow_expr" in data:
            self.setpoint_expr = str(data["flow_expr"])


SetFlowCommand = PressureSetFlowCommand
