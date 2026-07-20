"""Command plugin for enabling or disabling a pressure-gauge channel."""

from __future__ import annotations

from typing import Any

from qtpy.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.pressure_control.engine import PressureControllerEngine


class PressureGaugeChannelCommand(CommandPlugin):
    """Enable or disable a pressure gauge channel using runtime expressions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.channel_expr: str = "1"
        self.enabled_expr: str = "True"

    @property
    def name(self) -> str:
        return "Set Gauge Channel"

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"pressure"})

    def execute(self) -> None:
        channel = int(self.eval(self.channel_expr))
        enabled = bool(self.eval(self.enabled_expr))
        PressureControllerEngine.instance().set_gauge_channel_enabled(channel, enabled)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        channel_edit = QLineEdit(self.channel_expr, widget)
        enabled_edit = QLineEdit(self.enabled_expr, widget)

        def _apply() -> None:
            self.channel_expr = channel_edit.text().strip() or "1"
            self.enabled_expr = enabled_edit.text().strip() or "True"

        channel_edit.editingFinished.connect(_apply)
        enabled_edit.editingFinished.connect(_apply)
        layout.addRow("Channel expression:", channel_edit)
        layout.addRow("Enabled expression:", enabled_edit)
        layout.addRow(
            QLabel(
                "<i>Expressions are evaluated when the command runs, so you can drive them from script variables.</i>",
                widget,
            )
        )
        return widget

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data["channel_expr"] = self.channel_expr
        data["enabled_expr"] = self.enabled_expr
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        if "channel_expr" in data:
            self.channel_expr = str(data["channel_expr"])
        if "enabled_expr" in data:
            self.enabled_expr = str(data["enabled_expr"])
