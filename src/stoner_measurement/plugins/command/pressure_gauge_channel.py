"""Command plugin for enabling or disabling a pressure-gauge channel."""

from __future__ import annotations

from typing import Any

from qtpy.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.pressure_control.engine import PressureControllerEngine


class PressureGaugeChannelCommand(CommandPlugin):
    """Enable or disable a pressure gauge channel using runtime expressions.

    Use this command to switch a controllable gauge channel on or off at a
    particular step. On **General**, enter **Channel expression** and **Enabled
    expression**. They are evaluated in the live sequence namespace on each
    execution and converted to an integer channel and Boolean enable state.
    Blank fields revert to ``1`` and ``True`` respectively.

    The action uses the shared pressure engine and the connected driver's
    channel-control capability. Configure the controller in the pressure panel
    first. This command publishes no readings; use Pressure Monitor to record
    the resulting gauge state.

    Attributes:
        channel_expr (str):
            Integer channel expression; defaults to "1".
        enabled_expr (str):
            Boolean enable expression; defaults to "True".
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
        With a sequence instance named ``pressure_gauge_channel``, use
        the QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            pressure_gauge_channel.channel_expr = "1"
            pressure_gauge_channel.enabled_expr = "True"
    """

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
