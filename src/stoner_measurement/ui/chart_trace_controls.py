"""Shared controls for recording controller charts to the sequence engine."""

from __future__ import annotations

from qtpy.QtCore import QSignalBlocker
from qtpy.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from stoner_measurement.core.chart_trace import ChartTrace
from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.qt_compat import pyqtSlot


class ChartTraceControls(QWidget):
    """Select and record a named engine trace from a chart's incoming samples."""

    def __init__(self, engine: SequenceEngine | None, name: str, parent: QWidget) -> None:
        super().__init__(parent)
        self._engine = engine
        self._owner = object()
        self._trace: ChartTrace | None = None
        self._samples: dict[tuple[str, str], float] = {}

        self.enabled = QCheckBox("Write data to Trace", self)
        self.name = QLineEdit(name, self)
        self.name.setPlaceholderText("Trace name")
        self.name.setAccessibleName("Trace name")
        self._message = QLabel(self)
        self._message.setWordWrap(True)
        self._message.hide()
        row = QHBoxLayout()
        row.addWidget(self.enabled)
        row.addWidget(self.name, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self._message)
        self.setEnabled(engine is not None)
        self.enabled.toggled.connect(self._toggle)
        self.name.textEdited.connect(self._message.hide)

    @pyqtSlot(bool)
    def _toggle(self, checked: bool) -> None:
        if not checked:
            self._trace = None
            self._samples.clear()
            self.name.setEnabled(True)
        elif self._engine is not None:
            try:
                self._trace = self._engine.register_chart_trace(self.name.text(), self._owner)
            except ValueError as exc:
                with QSignalBlocker(self.enabled):
                    self.enabled.setChecked(False)
                self._message.setText(str(exc))
                self._message.show()
                return
            self.name.setText(self.name.text().strip())
            self.name.setEnabled(False)
        self._message.hide()

    def collect(self, channel: str, value: float, unit: str) -> None:
        """Stage one chart series value for the current update."""
        if self._trace is not None:
            self._samples[channel, unit] = value

    def commit(self, timestamp: float) -> None:
        """Write the staged chart series values as a single timestamped row."""
        if self._engine is not None and self._trace is not None and self._samples:
            samples, self._samples = self._samples, {}
            self._engine.append_chart_sample(self._trace, timestamp, samples)
