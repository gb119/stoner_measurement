"""Reusable NI-DAQmx input and output trigger configuration widgets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from qtpy.QtCore import QPointF, QRectF, Qt  # type: ignore[attr-defined]
from qtpy.QtGui import QPainter, QPalette, QPen, QPolygonF
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QSizePolicy,
    QWidget,
)

from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.ui.widgets.si_spinbox import SISpinBox


class DaqmxInputTriggerMode(StrEnum):
    """Supported sources for starting an input task."""

    IMMEDIATE = "immediate"
    DIGITAL = "digital"
    ANALOG = "analog"


class DaqmxTriggerEdge(StrEnum):
    """Active edge or slope of an input trigger."""

    RISING = "rising"
    FALLING = "falling"


class DaqmxTriggerIdleState(StrEnum):
    """Resting state of a generated digital trigger pulse."""

    LOW = "low"
    HIGH = "high"


@dataclass(frozen=True)
class DaqmxInputTrigger:
    """Serializable input-trigger settings."""

    mode: DaqmxInputTriggerMode = DaqmxInputTriggerMode.IMMEDIATE
    edge: DaqmxTriggerEdge = DaqmxTriggerEdge.RISING
    terminal: str = ""
    analog_level: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "mode": self.mode.value,
            "edge": self.edge.value,
            "terminal": self.terminal,
            "analog_level": self.analog_level,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> DaqmxInputTrigger:
        """Restore settings from a JSON-compatible mapping."""
        return cls(
            mode=DaqmxInputTriggerMode(str(value.get("mode", DaqmxInputTriggerMode.IMMEDIATE))),
            edge=DaqmxTriggerEdge(str(value.get("edge", DaqmxTriggerEdge.RISING))),
            terminal=str(value.get("terminal", "")),
            analog_level=float(value.get("analog_level", 0.0)),
        )


@dataclass(frozen=True)
class DaqmxOutputTrigger:
    """Serializable hardware-timed digital output-trigger settings.

    ``phase_angle`` expresses normalized position in the generated scan: 0° is
    the start and 360° is the end. It does not imply a sinusoidal waveform.
    The output remains at ``idle_state`` through the phase reference and delay,
    switches to the opposite state for its configured high or low time, then
    returns to idle for at least the complementary time.
    """

    enabled: bool = False
    line: str = ""
    idle_state: DaqmxTriggerIdleState = DaqmxTriggerIdleState.LOW
    phase_angle: float = 0.0
    delay: float = 10e-9
    high_time: float = 10e-9
    low_time: float = 10e-9

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "enabled": self.enabled,
            "line": self.line,
            "idle_state": self.idle_state.value,
            "phase_angle": self.phase_angle,
            "delay": self.delay,
            "high_time": self.high_time,
            "low_time": self.low_time,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> DaqmxOutputTrigger:
        """Restore settings from a JSON-compatible mapping."""
        return cls(
            enabled=bool(value.get("enabled", False)),
            line=str(value.get("line", "")),
            idle_state=DaqmxTriggerIdleState(
                str(value.get("idle_state", DaqmxTriggerIdleState.LOW))
            ),
            phase_angle=float(value.get("phase_angle", 0.0)),
            delay=float(value.get("delay", 10e-9)),
            high_time=float(value.get("high_time", 10e-9)),
            low_time=float(value.get("low_time", 10e-9)),
        )


def _select_combo_data(combo: QComboBox, value: Any) -> None:
    """Select *value* from a combo box when present."""
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _set_editable_items(combo: QComboBox, values: list[str], current: str) -> None:
    """Replace editable combo choices while retaining the current text."""
    combo.blockSignals(True)
    try:
        combo.clear()
        combo.addItems(values)
        combo.setCurrentText(current)
    finally:
        combo.blockSignals(False)


class DaqmxInputTriggerWidget(QGroupBox):
    """Configure the external signal that starts a DAQmx input task."""

    trigger_changed = pyqtSignal(object)

    _MODE_LABELS = {
        DaqmxInputTriggerMode.IMMEDIATE: "Immediate (software start)",
        DaqmxInputTriggerMode.DIGITAL: "Digital input",
        DaqmxInputTriggerMode.ANALOG: "Analogue input",
    }
    _EDGE_LABELS = {
        DaqmxTriggerEdge.RISING: "Rising",
        DaqmxTriggerEdge.FALLING: "Falling",
    }

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        trigger: DaqmxInputTrigger | None = None,
    ) -> None:
        super().__init__("Input triggering", parent)
        self._updating = False
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        form = QFormLayout(self)

        self.mode_combo = QComboBox(self)
        for mode, label in self._MODE_LABELS.items():
            self.mode_combo.addItem(label, mode.value)
        form.addRow("Start trigger", self.mode_combo)

        self.edge_combo = QComboBox(self)
        for edge, label in self._EDGE_LABELS.items():
            self.edge_combo.addItem(label, edge.value)
        form.addRow("Trigger edge", self.edge_combo)

        self.terminal_combo = QComboBox(self)
        self.terminal_combo.setEditable(True)
        self.terminal_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.terminal_combo.setPlaceholderText("e.g. /Dev1/PFI0")
        form.addRow("Trigger terminal", self.terminal_combo)

        self.level_spin = SISpinBox(self, value=0.0, suffix="V", siPrefix=True)
        self.level_spin.setMinimum(-1_000_000.0)
        self.level_spin.setMaximum(1_000_000.0)
        form.addRow("Analogue trigger level", self.level_spin)

        self.mode_combo.currentIndexChanged.connect(self._controls_changed)
        self.edge_combo.currentIndexChanged.connect(self._controls_changed)
        self.terminal_combo.currentTextChanged.connect(self._controls_changed)
        self.level_spin.valueChanged.connect(self._controls_changed)
        self.set_trigger(trigger or DaqmxInputTrigger())
        self.layout().activate()
        self.setFixedSize(self.sizeHint())

    def trigger(self) -> DaqmxInputTrigger:
        """Return the current input-trigger settings."""
        return DaqmxInputTrigger(
            mode=DaqmxInputTriggerMode(self.mode_combo.currentData()),
            edge=DaqmxTriggerEdge(self.edge_combo.currentData()),
            terminal=self.terminal_combo.currentText().strip(),
            analog_level=float(self.level_spin.value()),
        )

    def set_trigger(self, trigger: DaqmxInputTrigger) -> None:
        """Restore input-trigger settings without losing a custom terminal."""
        self._updating = True
        try:
            _select_combo_data(self.mode_combo, trigger.mode.value)
            _select_combo_data(self.edge_combo, trigger.edge.value)
            self.terminal_combo.setCurrentText(trigger.terminal)
            self.level_spin.setValue(trigger.analog_level)
            self._update_enabled_state()
        finally:
            self._updating = False

    def set_available_terminals(self, terminals: list[str] | tuple[str, ...]) -> None:
        """Populate discovered DAQmx routes while retaining manual entry."""
        current = self.terminal_combo.currentText()
        _set_editable_items(self.terminal_combo, sorted(set(terminals)), current)

    def _controls_changed(self, *_args: object) -> None:
        self._update_enabled_state()
        if not self._updating:
            self.trigger_changed.emit(self.trigger())

    def _update_enabled_state(self) -> None:
        mode = DaqmxInputTriggerMode(self.mode_combo.currentData())
        active = mode is not DaqmxInputTriggerMode.IMMEDIATE
        self.edge_combo.setEnabled(active)
        self.terminal_combo.setEnabled(active)
        self.level_spin.setEnabled(mode is DaqmxInputTriggerMode.ANALOG)


class DaqmxTriggerPulsePreview(QWidget):
    """Compact, palette-aware preview of the configured output pulse."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._trigger = DaqmxOutputTrigger()
        self.setMinimumHeight(106)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_trigger(self, trigger: DaqmxOutputTrigger) -> None:
        """Set the settings represented by the preview."""
        self._trigger = trigger
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override name
        """Draw a focused phase/delay/active/idle pulse using the active palette."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10, 8, -10, -18)
        palette = self.palette()
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid), 1))
        painter.drawRect(rect)

        if not self._trigger.enabled:
            painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Output trigger disabled")
            return

        pulse_rect = rect.adjusted(4, 22, -4, 0)
        phase_x = float(pulse_rect.left())
        marker_pen = QPen(palette.color(QPalette.ColorRole.Highlight), 1)
        marker_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(marker_pen)
        painter.drawLine(
            QPointF(phase_x, rect.top() + 17),
            QPointF(phase_x, pulse_rect.bottom()),
        )

        delay_width = pulse_rect.width() * (0.25 if self._trigger.delay > 0 else 0.0)
        pulse_time = max(self._trigger.high_time, 0.0) + max(self._trigger.low_time, 0.0)
        active_time = (
            self._trigger.high_time
            if self._trigger.idle_state is DaqmxTriggerIdleState.LOW
            else self._trigger.low_time
        )
        active_fraction = max(active_time, 0.0) / pulse_time if pulse_time else 0.5
        active_fraction = min(max(active_fraction, 0.2), 0.8)
        pulse_width = pulse_rect.width() - delay_width
        widths = [delay_width, pulse_width * active_fraction, pulse_width * (1 - active_fraction)]
        x0 = float(pulse_rect.left())
        x1 = x0 + widths[0]
        x2 = x1 + widths[1]
        x3 = float(pulse_rect.right() - 1)
        high_y = float(pulse_rect.top() + pulse_rect.height() * 0.18)
        low_y = float(pulse_rect.bottom() - pulse_rect.height() * 0.18)
        first_y, second_y = (
            (low_y, high_y)
            if self._trigger.idle_state is DaqmxTriggerIdleState.LOW
            else (high_y, low_y)
        )
        points = QPolygonF(
            [
                QPointF(x0, first_y),
                QPointF(x1, first_y),
                QPointF(x1, second_y),
                QPointF(x2, second_y),
                QPointF(x2, first_y),
                QPointF(x3, first_y),
            ]
        )
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Highlight), 2))
        painter.drawPolyline(points)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        painter.drawText(
            rect.adjusted(4, 0, -4, 0),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
            f"Phase reference {self._trigger.phase_angle:g} deg",
        )
        label_top = pulse_rect.bottom() + 1
        for left, width, label in zip(
            (x0, x1, x2), widths, ("delay", "active", "idle"), strict=True
        ):
            if width >= 24:
                painter.drawText(
                    QRectF(left, label_top, width, 16), Qt.AlignmentFlag.AlignCenter, label
                )


class DaqmxOutputTriggerWidget(QGroupBox):
    """Configure a hardware-timed digital trigger pulse for external equipment."""

    trigger_changed = pyqtSignal(object)

    _IDLE_LABELS = {
        DaqmxTriggerIdleState.LOW: "Low",
        DaqmxTriggerIdleState.HIGH: "High",
    }

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        trigger: DaqmxOutputTrigger | None = None,
    ) -> None:
        super().__init__("Output triggering", parent)
        self._updating = False
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(self)
        left_form = QFormLayout()
        left_form.setContentsMargins(0, 0, 0, 0)
        right_form = QFormLayout()
        right_form.setContentsMargins(0, 0, 0, 0)

        self.enabled_check = QCheckBox("Generate an external trigger pulse", self)
        layout.addWidget(self.enabled_check, 0, 0, 1, 2)
        self.line_combo = QComboBox(self)
        self.line_combo.setEditable(True)
        self.line_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.line_combo.setMinimumContentsLength(16)
        self.line_combo.setPlaceholderText("e.g. Dev1/port0/line0")
        left_form.addRow("Digital output line", self.line_combo)

        self.idle_combo = QComboBox(self)
        for state, label in self._IDLE_LABELS.items():
            self.idle_combo.addItem(label, state.value)
        right_form.addRow("Idle state", self.idle_combo)

        self.phase_angle_spin = SISpinBox(self, value=0.0, suffix="deg")
        self.phase_angle_spin.setMinimum(0.0)
        self.phase_angle_spin.setMaximum(360.0)
        self.phase_angle_spin.setToolTip(
            "Normalized position in the generated scan: 0° is the start and 360° is the end."
        )
        left_form.addRow("Phase angle", self.phase_angle_spin)

        self.delay_spin = self._time_spin()
        self.high_time_spin = self._time_spin()
        self.low_time_spin = self._time_spin()
        left_form.addRow("Trigger delay", self.delay_spin)
        right_form.addRow("High time", self.high_time_spin)
        right_form.addRow("Low time", self.low_time_spin)

        layout.addLayout(left_form, 1, 0)
        layout.addLayout(right_form, 1, 1)

        self.preview = DaqmxTriggerPulsePreview(self)
        layout.addWidget(self.preview, 2, 0, 1, 2)

        self.enabled_check.toggled.connect(self._controls_changed)
        self.line_combo.currentTextChanged.connect(self._controls_changed)
        self.idle_combo.currentIndexChanged.connect(self._controls_changed)
        self.phase_angle_spin.valueChanged.connect(self._controls_changed)
        self.delay_spin.valueChanged.connect(self._controls_changed)
        self.high_time_spin.valueChanged.connect(self._controls_changed)
        self.low_time_spin.valueChanged.connect(self._controls_changed)
        self.set_trigger(trigger or DaqmxOutputTrigger())
        self.layout().activate()
        self.setFixedSize(self.sizeHint())

    def _time_spin(self) -> SISpinBox:
        spin = SISpinBox(self, value=10e-9, suffix="s", siPrefix=True)
        spin.setMinimum(0.0)
        spin.setMaximum(86_400.0)
        return spin

    def trigger(self) -> DaqmxOutputTrigger:
        """Return the current output-trigger settings."""
        return DaqmxOutputTrigger(
            enabled=self.enabled_check.isChecked(),
            line=self.line_combo.currentText().strip(),
            idle_state=DaqmxTriggerIdleState(self.idle_combo.currentData()),
            phase_angle=float(self.phase_angle_spin.value()),
            delay=float(self.delay_spin.value()),
            high_time=float(self.high_time_spin.value()),
            low_time=float(self.low_time_spin.value()),
        )

    def set_trigger(self, trigger: DaqmxOutputTrigger) -> None:
        """Restore output-trigger settings without losing a custom line."""
        self._updating = True
        try:
            self.enabled_check.setChecked(trigger.enabled)
            self.line_combo.setCurrentText(trigger.line)
            _select_combo_data(self.idle_combo, trigger.idle_state.value)
            self.phase_angle_spin.setValue(trigger.phase_angle)
            self.delay_spin.setValue(trigger.delay)
            self.high_time_spin.setValue(trigger.high_time)
            self.low_time_spin.setValue(trigger.low_time)
            self._update_enabled_state()
            self.preview.set_trigger(trigger)
        finally:
            self._updating = False

    def set_available_lines(self, lines: list[str] | tuple[str, ...]) -> None:
        """Populate discovered digital output lines while retaining manual entry."""
        current = self.line_combo.currentText()
        _set_editable_items(self.line_combo, sorted(set(lines)), current)

    def _controls_changed(self, *_args: object) -> None:
        self._update_enabled_state()
        trigger = self.trigger()
        self.preview.set_trigger(trigger)
        if not self._updating:
            self.trigger_changed.emit(trigger)

    def _update_enabled_state(self) -> None:
        enabled = self.enabled_check.isChecked()
        for control in (
            self.line_combo,
            self.idle_combo,
            self.phase_angle_spin,
            self.delay_spin,
            self.high_time_spin,
            self.low_time_spin,
        ):
            control.setEnabled(enabled)


__all__ = [
    "DaqmxInputTrigger",
    "DaqmxInputTriggerMode",
    "DaqmxInputTriggerWidget",
    "DaqmxOutputTrigger",
    "DaqmxOutputTriggerWidget",
    "DaqmxTriggerEdge",
    "DaqmxTriggerIdleState",
    "DaqmxTriggerPulsePreview",
]
