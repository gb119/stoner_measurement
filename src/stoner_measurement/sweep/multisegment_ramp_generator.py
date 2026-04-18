"""Multi-segment ramp sweep generator."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pyqtgraph as pg
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.sweep.base import BaseSweepGenerator

_DEFAULT_POLL_SECONDS = 0.05


class MultiSegmentRampSweepGenerator(BaseSweepGenerator):
    """Sweep generator that ramps through target/rate segments."""

    def __init__(
        self,
        *,
        start: float = 0.0,
        segments: list[tuple[float, float, bool]] | None = None,
        poll_seconds: float = _DEFAULT_POLL_SECONDS,
        state_sweep=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(state_sweep=state_sweep, parent=parent)
        self._start = float(start)
        self._segments: list[tuple[float, float, bool]] = segments or [(1.0, 0.1, True)]
        self._poll_seconds = max(0.0, float(poll_seconds))

    @property
    def start(self) -> float:
        return self._start

    @start.setter
    def start(self, value: float) -> None:
        self._start = float(value)
        self._invalidate()

    @property
    def segments(self) -> list[tuple[float, float, bool]]:
        return list(self._segments)

    @segments.setter
    def segments(self, value: list[tuple[float, float, bool]]) -> None:
        cleaned: list[tuple[float, float, bool]] = []
        for target, rate, measure in value:
            cleaned.append((float(target), float(rate), bool(measure)))
        self._segments = cleaned or [(1.0, 0.1, True)]
        self._invalidate()

    @property
    def poll_seconds(self) -> float:
        return self._poll_seconds

    @poll_seconds.setter
    def poll_seconds(self, value: float) -> None:
        self._poll_seconds = max(0.0, float(value))
        self._invalidate()

    def iter_points(self) -> Iterator[tuple[int, float, int, bool]]:
        plugin = self.state_sweep
        if plugin is None:
            return
        if not self._segments:
            return

        plugin.set_state(float(self._start))
        while not plugin.is_at_target():
            if self._poll_seconds > 0.0:
                time.sleep(self._poll_seconds)

        stage_index = 0
        target, rate, measure_flag = self._segments[stage_index]
        plugin.set_rate(float(rate))
        plugin.set_target(float(target))

        ix = 0
        while True:
            current_value = float(plugin.get_state())
            yield ix, current_value, stage_index, bool(measure_flag)
            ix += 1

            if plugin.is_at_target():
                stage_index += 1
                if stage_index >= len(self._segments):
                    return
                target, rate, measure_flag = self._segments[stage_index]
                plugin.set_rate(float(rate))
                plugin.set_target(float(target))

            if self._poll_seconds > 0.0:
                time.sleep(self._poll_seconds)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        return MultiSegmentRampSweepWidget(generator=self, parent=parent)

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "MultiSegmentRampSweepGenerator",
            "start": self._start,
            "segments": [[target, rate, measure] for target, rate, measure in self._segments],
            "poll_seconds": self._poll_seconds,
        }

    @classmethod
    def _from_json_data(cls, data: dict[str, Any], *, state_sweep=None, parent: QObject | None = None):
        segments = [(float(target), float(rate), bool(measure)) for target, rate, measure in data.get("segments", [])]
        return cls(
            start=float(data.get("start", 0.0)),
            segments=segments,
            poll_seconds=float(data.get("poll_seconds", _DEFAULT_POLL_SECONDS)),
            state_sweep=state_sweep,
            parent=parent,
        )


class MultiSegmentRampSweepWidget(QWidget):
    """Configuration widget for MultiSegmentRampSweepGenerator."""

    def __init__(self, generator: MultiSegmentRampSweepGenerator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._generator = generator
        self._segment_curves: list = []
        self._build_ui()
        self._populate_from_generator()
        self._refresh_preview()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        form = QFormLayout()
        self._start_spin = pg.SpinBox()
        self._start_spin.setOpts(bounds=(-1e12, 1e12), decimals=6)
        self._start_spin.valueChanged.connect(self._on_start_changed)
        form.addRow("Start value:", self._start_spin)

        self._poll_spin = pg.SpinBox()
        self._poll_spin.setOpts(bounds=(0.0, 60.0), decimals=6, suffix="s")
        self._poll_spin.valueChanged.connect(self._on_poll_changed)
        form.addRow("Poll interval:", self._poll_spin)
        root.addLayout(form)

        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["Target", "Rate", "Measure"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._table)

        controls = QHBoxLayout()
        add_btn = QPushButton("Add Segment", self)
        remove_btn = QPushButton("Remove Segment", self)
        add_btn.clicked.connect(self._add_row)
        remove_btn.clicked.connect(self._remove_row)
        controls.addWidget(add_btn)
        controls.addWidget(remove_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        self._preview = pg.PlotWidget(self)
        self._preview.setLabel("bottom", "Time")
        self._preview.setLabel("left", "Value")
        root.addWidget(self._preview)
        root.addWidget(QLabel("Preview uses green/red segment lines for measure true/false.", self))

    def _build_target_spin(self, value: float) -> pg.SpinBox:
        spin = pg.SpinBox(self._table)
        spin.setOpts(bounds=(-1e12, 1e12), decimals=6)
        spin.setValue(float(value))
        spin.valueChanged.connect(self._sync_segments_from_table)
        return spin

    def _build_rate_spin(self, value: float) -> pg.SpinBox:
        spin = pg.SpinBox(self._table)
        spin.setOpts(bounds=(0.0, 1e12), decimals=6)
        spin.setValue(max(0.0, float(value)))
        spin.valueChanged.connect(self._sync_segments_from_table)
        return spin

    def _build_measure_checkbox(self, value: bool) -> QCheckBox:
        check = QCheckBox(self._table)
        check.setChecked(bool(value))
        check.stateChanged.connect(self._sync_segments_from_table)
        return check

    def _add_row(self) -> None:
        self._table.insertRow(self._table.rowCount())
        row = self._table.rowCount() - 1
        self._table.setCellWidget(row, 0, self._build_target_spin(0.0))
        self._table.setCellWidget(row, 1, self._build_rate_spin(0.1))
        self._table.setCellWidget(row, 2, self._build_measure_checkbox(True))
        self._sync_segments_from_table()

    def _remove_row(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            row = self._table.rowCount() - 1
        if row >= 0:
            self._table.removeRow(row)
        if self._table.rowCount() == 0:
            self._add_row()
        self._sync_segments_from_table()

    def _populate_from_generator(self) -> None:
        self._start_spin.setValue(self._generator.start)
        self._poll_spin.setValue(self._generator.poll_seconds)
        self._table.setRowCount(0)
        for target, rate, measure in self._generator.segments:
            self._table.insertRow(self._table.rowCount())
            row = self._table.rowCount() - 1
            self._table.setCellWidget(row, 0, self._build_target_spin(target))
            self._table.setCellWidget(row, 1, self._build_rate_spin(rate))
            self._table.setCellWidget(row, 2, self._build_measure_checkbox(measure))

    def _sync_segments_from_table(self) -> None:
        segments: list[tuple[float, float, bool]] = []
        for row in range(self._table.rowCount()):
            target_w = self._table.cellWidget(row, 0)
            rate_w = self._table.cellWidget(row, 1)
            measure_w = self._table.cellWidget(row, 2)
            target = float(target_w.value()) if isinstance(target_w, pg.SpinBox) else 0.0
            rate = float(rate_w.value()) if isinstance(rate_w, pg.SpinBox) else 0.0
            measure = bool(measure_w.isChecked()) if isinstance(measure_w, QCheckBox) else True
            segments.append((target, rate, measure))
        self._generator.segments = segments
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self._preview.clear()
        current = float(self._generator.start)
        current_time = 0.0
        for target, rate, measure in self._generator.segments:
            safe_rate = abs(float(rate))
            duration = abs(float(target) - current) / safe_rate if safe_rate > 0.0 else 0.0
            x_vals = [current_time, current_time + duration]
            y_vals = [current, float(target)]
            pen = pg.mkPen(color=(0, 200, 0) if measure else (200, 0, 0), width=2)
            self._preview.plot(x_vals, y_vals, pen=pen)
            current = float(target)
            current_time += duration

    def _on_start_changed(self, value: float) -> None:
        self._generator.start = float(value)
        self._refresh_preview()

    def _on_poll_changed(self, value: float) -> None:
        self._generator.poll_seconds = float(value)
