"""Shared implementation for commands that set an engine target."""

from __future__ import annotations

import math
import time
from abc import abstractmethod
from typing import Any

from qtpy.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.ui.widgets import SISpinBox


class SetEngineStateCommand(CommandPlugin):
    """Base class for commands that set, optionally await, and snapshot an engine state."""

    setpoint_suffix = ""
    poll_interval = 0.5

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setpoint_expr: str = "0.0"
        self.wait_expr: str = "True"
        self._final_values: dict[str, float] = {}

    @property
    @abstractmethod
    def output_names(self) -> tuple[str, ...]:
        """Names of scalar values captured from the final engine snapshot."""

    @abstractmethod
    def _ensure_engine(self):
        """Return a connected controller engine."""

    @abstractmethod
    def _set_target(self, engine, setpoint: float) -> None:
        """Apply *setpoint* to *engine*."""

    @abstractmethod
    def _read_state(self, engine):
        """Return a fresh engine state, falling back to the cached state if necessary."""

    @abstractmethod
    def _target_reached(self, state, setpoint: float) -> bool:
        """Return whether *state* reports that *setpoint* has been reached."""

    @abstractmethod
    def _state_values(self, state) -> dict[str, float]:
        """Convert *state* to the published scalar output mapping."""

    def _add_specific_config(self, layout: QFormLayout, widget: QWidget) -> None:
        """Add engine-specific configuration rows."""

    def _specific_to_json(self) -> dict[str, Any]:
        """Return engine-specific serialised settings."""
        return {}

    def _restore_specific_json(self, data: dict[str, Any]) -> None:
        """Restore engine-specific serialised settings."""

    def _stop_requested(self) -> bool:
        sequence_engine = self.sequence_engine
        thread = getattr(sequence_engine, "_thread", None)
        stop_event = getattr(thread, "_stop_event", None)
        return bool(stop_event is not None and stop_event.is_set())

    def execute(self) -> None:
        """Set the evaluated target, optionally wait for it, and capture final state."""
        setpoint = self.eval_float(self.setpoint_expr)
        wait_for_target = bool(self.eval(self.wait_expr))
        engine = self._ensure_engine()
        self._set_target(engine, setpoint)
        state = self._read_state(engine)
        while wait_for_target and not self._target_reached(state, setpoint):
            if self._stop_requested():
                break
            time.sleep(self.poll_interval)
            state = self._read_state(engine)
        self._final_values = self._state_values(state)

    def output_value(self, name: str) -> float:
        """Return one value from the state snapshot captured by :meth:`execute`."""
        return self._final_values.get(name, math.nan)

    def reported_values(self) -> dict[str, str]:
        """Expose the final engine-state snapshot through the scalar catalogue."""
        var = self.instance_name
        return {
            f"{var}:{name}": f"{var}.output_value({name!r})"
            for name in self.output_names
        }

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Build the common expression controls plus engine-specific settings."""
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        self._add_specific_config(layout, widget)

        setpoint = SISpinBox(
            widget,
            value=self.setpoint_expr,
            suffix=self.setpoint_suffix,
            siPrefix=True,
            allow_expressions=True,
        )
        setpoint.setObjectName("setpoint_expression")
        setpoint.setToolTip("Numeric expression evaluated in the sequence namespace when the command runs.")
        setpoint.editingFinished.connect(lambda: setattr(self, "setpoint_expr", str(setpoint.value())))
        layout.addRow("Setpoint expression:", setpoint)

        wait = QLineEdit(self.wait_expr, widget)
        wait.setObjectName("wait_expression")
        wait.setToolTip("Boolean expression evaluated once after setting the target. Default: True.")
        wait.editingFinished.connect(
            lambda: setattr(self, "wait_expr", wait.text().strip() or "True")
        )
        layout.addRow("Wait expression:", wait)
        layout.addRow(
            QLabel(
                "<i>The final fresh engine state is published as this command's scalar outputs.</i>",
                widget,
            )
        )
        return widget

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data.update(
            {
                "setpoint_expr": self.setpoint_expr,
                "wait_expr": self.wait_expr,
                **self._specific_to_json(),
            }
        )
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        if "setpoint_expr" in data:
            self.setpoint_expr = str(data["setpoint_expr"])
        self.wait_expr = str(data.get("wait_expr", "True"))
        self._restore_specific_json(data)
