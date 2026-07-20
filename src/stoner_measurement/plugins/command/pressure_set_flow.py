"""Command plugin for setting an MFC flow setpoint."""

from __future__ import annotations

from typing import Any

from qtpy.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.pressure_control.engine import PressureControllerEngine


class PressureSetFlowCommand(CommandPlugin):
    """Set the flow rate on a selected MFC channel using runtime expressions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.channel_expr: str = "1"
        self.flow_expr: str = "0.0"

    @property
    def name(self) -> str:
        return "Set MFC Flow"

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"pressure"})

    def execute(self) -> None:
        channel = int(self.eval(self.channel_expr))
        flow = float(self.eval(self.flow_expr))
        PressureControllerEngine.instance().set_flow_rate(channel, flow)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        channel_edit = QLineEdit(self.channel_expr, widget)
        flow_edit = QLineEdit(self.flow_expr, widget)

        def _apply() -> None:
            self.channel_expr = channel_edit.text().strip() or "1"
            self.flow_expr = flow_edit.text().strip() or "0.0"

        channel_edit.editingFinished.connect(_apply)
        flow_edit.editingFinished.connect(_apply)
        layout.addRow("Channel expression:", channel_edit)
        layout.addRow("Flow expression:", flow_edit)
        layout.addRow(
            QLabel(
                "<i>Both fields are Python expressions evaluated at execution time in the sequence namespace.</i>",
                widget,
            )
        )
        return widget

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data["channel_expr"] = self.channel_expr
        data["flow_expr"] = self.flow_expr
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        if "channel_expr" in data:
            self.channel_expr = str(data["channel_expr"])
        if "flow_expr" in data:
            self.flow_expr = str(data["flow_expr"])
