"""Command plugin for runtime editing of function-based scan generators."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qtpy.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QLineEdit, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.plugins.state_scan.base import StateScanPlugin
from stoner_measurement.plugins.trace.base import TracePlugin
from stoner_measurement.scan.function_generator import FunctionScanGenerator, WaveformType

_NUMERIC_PARAMETERS = ("amplitude", "offset", "periods", "exponent", "phase")


def _waveform_from_value(value: object) -> WaveformType:
    """Return a waveform enum from an enum, display value, or member name."""
    if isinstance(value, WaveformType):
        return value
    text = str(value).strip()
    for waveform in WaveformType:
        if text.casefold() in {waveform.value.casefold(), waveform.name.casefold()}:
            return waveform
    raise ValueError(f"Unknown function-scan waveform {value!r}.")


class EditFunctionScanCommand(CommandPlugin):
    """Change a later function-generator scan while a sequence is running.

    Use this command when a state scan or trace scan needs an initial function
    generator configuration that is replaced later in the same sequence. Place
    the command before the scan step that should use the new points. The target
    list contains sequence instances whose active scan generator is a
    :class:`FunctionScanGenerator`; both state-scan and trace-plugin instances
    are supported.

    The configuration tab provides a **Scan plugin** selector followed by
    optional **Amplitude**, **Offset**, **Periods**, **Points**, **Exponent**,
    **Phase**, and **Waveform** expressions. Leave a field blank to retain that
    generator setting exactly as it is. A non-blank field is evaluated in the
    sequence namespace when this command runs. Waveform accepts ``Sine``,
    ``Triangle``, ``Square``, or ``Sawtooth``, or an expression resolving to
    one of those values. Enable **Reconfigure scan plugin after editing** to
    call the target plugin's ``configure()`` method immediately afterwards.

    All supplied expressions are evaluated before any setting is changed, so
    an evaluation error leaves the generator untouched. If evaluation
    succeeds, the supplied settings are applied together and the scan values
    are regenerated immediately. This command does not execute the target scan
    and does not publish scalar outputs.

    Attributes:
        target_scan (str):
            Instance name of the state or trace scan to edit.
        amplitude_expr (str):
            Optional expression replacing the waveform amplitude.
        offset_expr (str):
            Optional expression replacing the waveform offset.
        periods_expr (str):
            Optional expression replacing the number of waveform periods.
        points_expr (str):
            Optional expression replacing the integer number of scan points.
        exponent_expr (str):
            Optional expression replacing the waveform exponent.
        waveform_expr (str):
            Optional waveform name or expression resolving to a waveform name.
        phase_expr (str):
            Optional expression replacing the phase in degrees.
        reconfigure_after_edit (bool):
            Whether generated sequence code calls ``configure()`` on the
            target scan plugin immediately after this command.
        instance_name (str):
            Inherited sequence-instance name for this command.
        sequence_engine (SequenceEngine | None):
            Inherited reference to the sequence engine and its live namespace.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Retarget a scan from the QtConsole before executing this command::

            edit_function_scan.target_scan = "field_scan"
            edit_function_scan.amplitude_expr = "next_amplitude"
            edit_function_scan.points_expr = "points_per_period * 2"
            edit_function_scan.waveform_expr = "Triangle"

        Clear a replacement to preserve the current generator setting::

            edit_function_scan.offset_expr = ""
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.target_scan = ""
        self.amplitude_expr = ""
        self.offset_expr = ""
        self.periods_expr = ""
        self.points_expr = ""
        self.exponent_expr = ""
        self.waveform_expr = ""
        self.phase_expr = ""
        self.reconfigure_after_edit = False

    @property
    def name(self) -> str:
        return "Edit Function Scan"

    def eligible_scans(self) -> list[StateScanPlugin | TracePlugin]:
        """Return sequence state and trace scans using a function generator."""
        engine = self.sequence_engine
        if engine is None:
            return []
        return [
            plugin
            for plugin in engine.step_plugins()
            if isinstance(plugin, (StateScanPlugin, TracePlugin))
            and isinstance(plugin.scan_generator, FunctionScanGenerator)
        ]

    def _target_plugin(self) -> StateScanPlugin | TracePlugin:
        for plugin in self.eligible_scans():
            if plugin.instance_name == self.target_scan:
                return plugin
        if not self.target_scan:
            raise RuntimeError("No function-based state or trace scan is selected.")
        raise RuntimeError(
            f"Scan plugin {self.target_scan!r} is not present in the sequence "
            "or no longer uses a Function Scan Generator."
        )

    def _evaluate_waveform(self) -> WaveformType | None:
        expression = self.waveform_expr.strip()
        if not expression:
            return None
        try:
            return _waveform_from_value(expression)
        except ValueError:
            return _waveform_from_value(self.eval(expression))

    def execute(self) -> None:
        """Evaluate replacements atomically, apply them, and regenerate the scan."""
        target = self._target_plugin()
        generator = target.scan_generator
        if not isinstance(generator, FunctionScanGenerator):
            raise RuntimeError(f"Scan plugin {self.target_scan!r} is not function-based.")

        replacements: dict[str, float | int | WaveformType] = {}
        for parameter in _NUMERIC_PARAMETERS:
            expression = str(getattr(self, f"{parameter}_expr")).strip()
            if expression:
                replacements[parameter] = self.eval_float(expression)
        if self.points_expr.strip():
            replacements["num_points"] = int(self.eval(self.points_expr))
        waveform = self._evaluate_waveform()
        if waveform is not None:
            replacements["waveform"] = waveform

        if replacements:
            for parameter, value in replacements.items():
                setattr(generator, parameter, value)
            _ = generator.values

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return the target picker and optional replacement-expression fields."""
        return _EditFunctionScanWidget(self, parent)

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Render the edit call followed by optional target reconfiguration."""
        lines = super().generate_action_code(indent, sub_steps, render_sub_step)
        if self.reconfigure_after_edit and self.target_scan:
            lines.insert(-1, f"{'    ' * indent}{self.target_scan}.configure()")
        return lines

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data.update(
            {
                "target_scan": self.target_scan,
                "amplitude_expr": self.amplitude_expr,
                "offset_expr": self.offset_expr,
                "periods_expr": self.periods_expr,
                "points_expr": self.points_expr,
                "exponent_expr": self.exponent_expr,
                "waveform_expr": self.waveform_expr,
                "phase_expr": self.phase_expr,
                "reconfigure_after_edit": self.reconfigure_after_edit,
            }
        )
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        self.target_scan = str(data.get("target_scan", ""))
        for parameter in (*_NUMERIC_PARAMETERS, "points", "waveform"):
            attribute = f"{parameter}_expr"
            setattr(self, attribute, str(data.get(attribute, "")))
        self.reconfigure_after_edit = bool(data.get("reconfigure_after_edit", False))


class _EditFunctionScanWidget(QWidget):
    """Configuration widget bound to an :class:`EditFunctionScanCommand`."""

    def __init__(self, command: EditFunctionScanCommand, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._command = command
        self._edits: dict[str, QLineEdit] = {}
        self._build_ui()
        engine = command.sequence_engine
        if engine is not None:
            engine.namespace_updated.connect(self.refresh_scan_list)

    def _build_ui(self) -> None:
        layout = QFormLayout(self)
        self._scan_combo = QComboBox(self)
        self._scan_combo.setObjectName("target_scan_plugin")
        self._scan_combo.currentIndexChanged.connect(self._on_scan_changed)
        layout.addRow("Scan plugin:", self._scan_combo)

        for parameter, label in (
            ("amplitude", "Amplitude:"),
            ("offset", "Offset:"),
            ("periods", "Periods:"),
            ("points", "Points:"),
            ("exponent", "Exponent:"),
            ("phase", "Phase (°):"),
        ):
            edit = QLineEdit(str(getattr(self._command, f"{parameter}_expr")), self)
            edit.setObjectName(f"{parameter}_expression")
            edit.setPlaceholderText("Retain current value/expression")
            edit.editingFinished.connect(
                lambda parameter=parameter, edit=edit: setattr(
                    self._command, f"{parameter}_expr", edit.text().strip()
                )
            )
            self._edits[parameter] = edit
            layout.addRow(label, edit)

        self._waveform_combo = QComboBox(self)
        self._waveform_combo.setObjectName("waveform_expression")
        self._waveform_combo.setEditable(True)
        self._waveform_combo.addItem("", "")
        for waveform in WaveformType:
            self._waveform_combo.addItem(waveform.value, waveform.value)
        self._waveform_combo.setEditText(self._command.waveform_expr)
        self._waveform_combo.lineEdit().setPlaceholderText("Retain current waveform")
        self._waveform_combo.currentTextChanged.connect(self._on_waveform_changed)
        layout.addRow("Waveform:", self._waveform_combo)

        self._reconfigure_check = QCheckBox(self)
        self._reconfigure_check.setObjectName("reconfigure_after_edit")
        self._reconfigure_check.setChecked(self._command.reconfigure_after_edit)
        self._reconfigure_check.toggled.connect(self._on_reconfigure_changed)
        layout.addRow("Reconfigure scan plugin after editing:", self._reconfigure_check)

        layout.addRow(
            QLabel(
                "<i>Blank fields retain the current generator setting. Non-blank fields are "
                "evaluated when this command runs.</i>",
                self,
            )
        )
        self.refresh_scan_list()

    def refresh_scan_list(self) -> None:
        """Refresh eligible state and trace scans while preserving the target."""
        configured = self._command.target_scan
        scans = self._command.eligible_scans()
        self._scan_combo.blockSignals(True)
        self._scan_combo.clear()
        for scan in scans:
            self._scan_combo.addItem(
                f"{scan.instance_name} ({scan.name})",
                scan.instance_name,
            )
        if not scans:
            self._scan_combo.addItem("No function-based state or trace scans available", "")
            self._scan_combo.model().item(0).setEnabled(False)
        selected = self._scan_combo.findData(configured)
        if selected < 0 and not configured and scans:
            selected = 0
        self._scan_combo.setCurrentIndex(selected)
        self._scan_combo.blockSignals(False)
        if selected >= 0:
            self._command.target_scan = str(self._scan_combo.itemData(selected))

    def _on_scan_changed(self, index: int) -> None:
        if index >= 0:
            self._command.target_scan = str(self._scan_combo.itemData(index) or "")

    def _on_waveform_changed(self, text: str) -> None:
        self._command.waveform_expr = text.strip()

    def _on_reconfigure_changed(self, checked: bool) -> None:
        self._command.reconfigure_after_edit = checked
