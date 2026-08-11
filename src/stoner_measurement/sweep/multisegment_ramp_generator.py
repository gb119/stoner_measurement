"""Multi-segment ramp sweep generator.

Provides a sweep generator that moves a controlled state through a sequence of
target/rate segments, yielding the live state value while the owning plugin
ramps towards each configured target in turn.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pyqtgraph as pg
from qtpy import QtGui
from qtpy.QtCore import QObject, Qt
from qtpy.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.sweep.base import BaseSweepGenerator
from stoner_measurement.ui.aspect_ratio_widget import (
    ContentWrappingTabWidget,
    MaximumAspectRatioWidget,
    set_table_visible_row_count,
)
from stoner_measurement.ui.generator_json import (
    load_generator_json,
    save_generator_json,
    set_generator_file_button_icons,
)
from stoner_measurement.ui.widgets import SISpinBox

_DEFAULT_POLL_SECONDS = 0.05
_SPINBOX_MAX_ABS = 1e9
_FLOAT_TOLERANCE = 1e-12


class MultiSegmentRampSweepGenerator(BaseSweepGenerator):
    """Ramp through a sequence of target/rate sweep segments.

    The generator first moves the owning state-sweep plugin to the configured
    start value, waits until that initial target is reached, then applies each
    configured ``(target, rate, measure)`` segment in sequence. The current
    live state is yielded repeatedly while each segment is in progress.

    Args:
        start (float):
            Initial state value set before the first segment begins.
        segments (list[tuple[float, float, bool]] | None):
            Sweep segments as ``(target, rate, measure)`` tuples.
        poll_seconds (float):
            Delay in seconds between state polls while waiting/ramping.
        start_timeout_seconds (float):
            Maximum time to wait for the initial start value to be reached
            before the sweep terminates early.
        state_sweep:
            Owning state-sweep plugin used to drive and read the controlled
            state.
        parent (QObject | None):
            Optional Qt parent object.

    Notes:
        The yielded stage index corresponds to the current segment index. This
        lets preview widgets distinguish repeated values occurring in different
        segments.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        start: float | str = 0.0,
        segments: list[tuple[float | str, float | str, bool]] | None = None,
        poll_seconds: float | str = _DEFAULT_POLL_SECONDS,
        start_timeout_seconds: float | str = 60.0,
        state_sweep=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(state_sweep=state_sweep, parent=parent)
        self._start = start
        self._segments: list[tuple[float | str, float | str, bool]] = (
            [(1.0, 0.1, True)] if segments is None else list(segments)
        )
        self._poll_seconds = poll_seconds
        self._start_timeout_seconds = start_timeout_seconds

    @property
    def start(self) -> float | str:
        """Return the configured start value.

        Returns:
            (float):
                Initial state value set before segment processing starts.
        """
        return self._start

    @start.setter
    def start(self, value: float | str) -> None:
        """Set the configured start value.

        Args:
            value (float):
                Initial state value set before segment processing starts.
        """
        self._start = value
        self._invalidate()

    @property
    def segments(self) -> list[tuple[float | str, float | str, bool]]:
        """Return configured sweep segments.

        Returns:
            (list[tuple[float, float, bool]]):
                Copy of configured ``(target, rate, measure)`` segments.
        """
        return list(self._segments)

    @segments.setter
    def segments(self, value: list[tuple[float | str, float | str, bool]]) -> None:
        """Set configured sweep segments.

        Args:
            value (list[tuple[float, float, bool]]):
                Segments as ``(target, rate, measure)`` tuples.
        """
        cleaned: list[tuple[float | str, float | str, bool]] = []
        for target, rate, measure in value:
            cleaned.append((target, rate, bool(measure)))
        self._segments = cleaned
        self._invalidate()

    @property
    def poll_seconds(self) -> float | str:
        """Return the polling interval.

        Returns:
            (float):
                Delay between state checks, in seconds.
        """
        return self._poll_seconds

    @poll_seconds.setter
    def poll_seconds(self, value: float | str) -> None:
        """Set the polling interval.

        Args:
            value (float):
                Delay between state checks, in seconds.
        """
        self._poll_seconds = value
        self._invalidate()

    @property
    def start_timeout_seconds(self) -> float | str:
        """Return the initial-start wait timeout.

        Returns:
            (float):
                Timeout in seconds used while waiting for the initial state to
                be reached.
        """
        return self._start_timeout_seconds

    @start_timeout_seconds.setter
    def start_timeout_seconds(self, value: float | str) -> None:
        """Set the initial-start wait timeout.

        Args:
            value (float):
                Timeout in seconds used while waiting for the initial state to
                be reached.
        """
        self._start_timeout_seconds = value
        self._invalidate()

    def iter_points(self) -> Iterator[tuple[int, float, int, bool]]:
        """Yield live sweep points while ramping through configured segments.

        Yields:
            (tuple[int, float, int, bool]):
                Tuples of ``(index, value, stage, measure_flag)`` where
                ``index`` counts yielded points, ``value`` is the live state,
                ``stage`` is the active segment index, and ``measure_flag`` is
                taken from the active segment configuration.

        Notes:
            If the start value is not reached within
            :attr:`start_timeout_seconds`, iteration stops early.
        """
        plugin = self.state_sweep
        if plugin is None:
            return
        if not self._segments:
            return

        if not plugin.start_from_current_value:
            plugin.set_state(self.eval_float(self._start))
            start_wait_started = time.monotonic()
            while not plugin.is_at_target():
                if (
                    self.eval_float(self._start_timeout_seconds) > 0.0
                    and (time.monotonic() - start_wait_started)
                    > self.eval_float(self._start_timeout_seconds)
                ):
                    return
                if self.eval_float(self._poll_seconds) > 0.0:
                    time.sleep(self.eval_float(self._poll_seconds))

        stage_index = 0
        target, rate, measure_flag = self._segments[stage_index]
        plugin.set_rate(self.eval_float(rate))
        plugin.set_target(self.eval_float(target))

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
                plugin.set_rate(self.eval_float(rate))
                plugin.set_target(self.eval_float(target))

            if self.eval_float(self._poll_seconds) > 0.0:
                time.sleep(self.eval_float(self._poll_seconds))

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return the configuration widget for this generator.

        Args:
            parent (QWidget | None):
                Optional parent widget.

        Returns:
            (QWidget):
                Widget bound to this generator instance.
        """
        return MultiSegmentRampSweepWidget(generator=self, parent=parent)

    def estimated_duration(self) -> float:
        """Return the estimated total sweep duration in seconds.

        Computes a conservative estimate of the full sweep runtime.

        The estimate includes:

        - the configured initial wait allowance for reaching :attr:`start`
        - the travel time for each configured segment,
          ``|target - previous_target| / rate``, converted using the owning
          plugin's configured rate time scale
        - one polling interval for each segment transition to account for
          control-loop and target-detection latency

        Returns ``float("inf")`` if any segment has a zero or negative rate.
        Returns ``0.0`` if there are no segments.

        Returns:
            (float):
                Total estimated sweep time in seconds.

        Examples:
            The estimate intentionally includes startup and polling overhead,
            so it is conservative rather than exact.

            >>> from qtpy.QtWidgets import QApplication
            >>> from stoner_measurement.plugins.state_sweep import MagnetControllerSweepPlugin
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.sweep import MultiSegmentRampSweepGenerator
            >>> plugin = MagnetControllerSweepPlugin()
            >>> gen = MultiSegmentRampSweepGenerator(
            ...     start=0.0, segments=[(2.0, 1.0, True), (0.0, 0.5, False)], state_sweep=plugin
            ... )
            >>> gen.estimated_duration()
            420.15
        """
        if not self._segments:
            return 0.0

        use_current = bool(
            self.state_sweep is not None and self.state_sweep.start_from_current_value
        )
        total = 0.0 if use_current else self.eval_float(self._start_timeout_seconds)
        prev = (
            float(self.state_sweep.get_state()) if use_current else self.eval_float(self._start)
        )
        for target, rate, _ in self._segments:
            target_value = self.eval_float(target)
            rate_value = self.eval_float(rate)
            if rate_value <= 0.0:
                return float("inf")
            total += self.duration_seconds_for_distance_rate(
                abs(target_value - prev), rate_value
            )
            prev = target_value

        poll_seconds = self.eval_float(self._poll_seconds)
        if poll_seconds > 0.0:
            total += poll_seconds * (len(self._segments) + 1)

        return total

    def _representation_details(self) -> str:
        """Return the start value and configured segment count."""
        count = len(self._segments)
        start = self._start if isinstance(self._start, str) else f"{self._start:g}"
        return f"start={start}, {count} {'segment' if count == 1 else 'segments'}"

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "MultiSegmentRampSweepGenerator",
            "start": self._start,
            "segments": [[target, rate, measure] for target, rate, measure in self._segments],
            "poll_seconds": self._poll_seconds,
            "start_timeout_seconds": self._start_timeout_seconds,
        }

    @classmethod
    def _from_json_data(
        cls, data: dict[str, Any], *, state_sweep=None, parent: QObject | None = None
    ):
        """Reconstruct a generator instance from serialised data.

        Args:
            data (dict[str, Any]):
                Serialised generator configuration.
            state_sweep:
                Owning state-sweep plugin for the reconstructed generator.
            parent (QObject | None):
                Optional Qt parent object.

        Returns:
            (MultiSegmentRampSweepGenerator):
                Reconstructed generator instance.
        """
        segments = [
            (target, rate, bool(measure))
            for target, rate, measure in data.get("segments", [])
        ]
        return cls(
            start=data.get("start", 0.0),
            segments=segments,
            poll_seconds=data.get("poll_seconds", _DEFAULT_POLL_SECONDS),
            start_timeout_seconds=data.get("start_timeout_seconds", 60.0),
            state_sweep=state_sweep,
            parent=parent,
        )


class MultiSegmentRampSweepWidget(QWidget):
    """Configuration widget for MultiSegmentRampSweepGenerator."""

    def __init__(
        self, generator: MultiSegmentRampSweepGenerator, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._generator = generator
        self._segment_curves: list = []
        self._build_ui()
        self._populate_from_generator()
        self._refresh_preview()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._tabs = ContentWrappingTabWidget(self)
        root.addWidget(self._tabs, alignment=Qt.AlignmentFlag.AlignTop)

        config_widget = QWidget(self)
        config_layout = QVBoxLayout(config_widget)
        config_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        form = QFormLayout()
        self._start_spin = SISpinBox(allow_expressions=True)
        self._start_spin.setOpts(bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), decimals=6)
        self._start_spin.valueChanged.connect(self._on_start_changed)
        form.addRow("Start value:", self._start_spin)

        self._poll_spin = SISpinBox(allow_expressions=True)
        self._poll_spin.setOpts(bounds=(0.0, 60.0), decimals=6, suffix="s")
        self._poll_spin.valueChanged.connect(self._on_poll_changed)
        form.addRow("Poll interval:", self._poll_spin)

        self._start_timeout_spin = SISpinBox(allow_expressions=True)
        self._start_timeout_spin.setOpts(bounds=(0.0, _SPINBOX_MAX_ABS), decimals=6, suffix="s")
        self._start_timeout_spin.valueChanged.connect(self._on_start_timeout_changed)
        form.addRow("Start wait timeout:", self._start_timeout_spin)
        config_layout.addLayout(form)

        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["Target", "Rate", "Measure"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        set_table_visible_row_count(self._table, 8)
        config_layout.addWidget(self._table)

        controls = QHBoxLayout()
        self._new_btn = QPushButton("New/Clear", self)
        self._load_btn = QPushButton("Load", self)
        self._save_btn = QPushButton("Save", self)
        self._add_btn = QPushButton("+ Segment", self)
        self._remove_btn = QPushButton("− Segment", self)
        set_generator_file_button_icons(self, self._new_btn, self._load_btn, self._save_btn)
        self._new_btn.clicked.connect(self._clear_segments)
        self._load_btn.clicked.connect(self._load_from_json)
        self._save_btn.clicked.connect(self._save_to_json)
        self._add_btn.clicked.connect(self._add_row)
        self._remove_btn.clicked.connect(self._remove_row)
        controls.addWidget(self._new_btn)
        controls.addWidget(self._load_btn)
        controls.addWidget(self._save_btn)
        controls.addWidget(self._add_btn, 1)
        controls.addWidget(self._remove_btn, 1)
        config_layout.addLayout(controls)
        self._tabs.addTab(config_widget, "Segments")

        preview_widget = QWidget(self)
        preview_layout = QVBoxLayout(preview_widget)
        self._preview = pg.PlotWidget(self)

        font = QtGui.QFont()
        font.setPointSize(10)
        font.setBold(True)
        font.setFamily("Arial")

        axis_pen = pg.mkPen(color="white", width=2)
        for axis_name, label in zip(["left", "bottom"], ["Value", "Time"]):
            axis = self._preview.getAxis(axis_name)
            axis.setTextPen(pg.mkPen("white"))
            axis.setTickFont(font)
            axis.setLabel(
                label,
                **{
                    "font-size": "11pt",
                    "font-family": "Arial",
                    "font-weight": "bold",
                    "color": "white",
                },
            )
            axis.setPen(axis_pen)

        self._current_marker = pg.ScatterPlotItem(
            pen=pg.mkPen(color=(255, 220, 0), width=2),
            brush=pg.mkBrush(0, 0, 0, 0),
            symbol="o",
            size=12,
        )
        self._preview.addItem(self._current_marker)
        self._preview_container = MaximumAspectRatioWidget(self._preview)
        preview_layout.addWidget(self._preview_container)
        preview_layout.addWidget(
            QLabel("Preview uses green/red segment lines for measure true/false.", self)
        )
        self._tabs.addTab(preview_widget, "Preview")

        self._generator.values_changed.connect(self._clear_current_marker)
        self._generator.current_point_changed.connect(self._on_current_point_changed)

    def _build_target_spin(self, value: float | str) -> SISpinBox:
        spin = SISpinBox(self._table, allow_expressions=True)
        spin.setOpts(bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), decimals=6)
        spin.setValue(value)
        spin.valueChanged.connect(self._sync_segments_from_table)
        return spin

    def _build_rate_spin(self, value: float | str) -> SISpinBox:
        spin = SISpinBox(self._table, allow_expressions=True)
        spin.setOpts(bounds=(0.0, _SPINBOX_MAX_ABS), decimals=6)
        spin.setValue(value)
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
        self._sync_segments_from_table()

    def _clear_segments(self) -> None:
        """Remove every sweep segment while preserving the other settings."""
        self._generator.segments = []
        self._populate_from_generator()
        self._refresh_preview()

    def _load_from_json(self) -> None:
        """Load a multi-segment sweep configuration selected by the user."""
        data = load_generator_json(self, "Load multi-segment sweep")
        if data is None:
            return
        if data.get("type") != "MultiSegmentRampSweepGenerator":
            QMessageBox.warning(
                self,
                "Unable to load configuration",
                "The file is not a multi-segment ramp sweep.",
            )
            return
        try:
            loaded = MultiSegmentRampSweepGenerator._from_json_data(
                data,
                state_sweep=self._generator.state_sweep,
            )
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Unable to load configuration", str(exc))
            return
        self._generator.start = loaded.start
        self._generator.poll_seconds = loaded.poll_seconds
        self._generator.start_timeout_seconds = loaded.start_timeout_seconds
        self._generator.segments = loaded.segments
        self._populate_from_generator()
        self._refresh_preview()

    def _save_to_json(self) -> None:
        """Save the current multi-segment sweep to a user-selected file."""
        save_generator_json(self, "Save multi-segment sweep", self._generator.to_json())

    def _populate_from_generator(self) -> None:
        self._start_spin.setValue(self._generator.start)
        self._poll_spin.setValue(self._generator.poll_seconds)
        self._start_timeout_spin.setValue(self._generator.start_timeout_seconds)
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
            target = target_w.value() if isinstance(target_w, SISpinBox) else 0.0
            rate = rate_w.value() if isinstance(rate_w, SISpinBox) else 0.0
            measure = bool(measure_w.isChecked()) if isinstance(measure_w, QCheckBox) else True
            segments.append((target, rate, measure))
        self._generator.segments = segments
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self._preview.clear()
        self._preview.addItem(self._current_marker)
        current = self._generator.eval_float(self._generator.start)
        current_time = 0.0
        for target, rate, measure in self._generator.segments:
            target_value = self._generator.eval_float(target)
            rate_magnitude = abs(self._generator.eval_float(rate))
            duration = (
                self._generator.duration_seconds_for_distance_rate(
                    abs(target_value - current),
                    rate_magnitude,
                )
                if rate_magnitude > 0.0
                else 0.0
            )
            x_vals = [current_time, current_time + duration]
            y_vals = [current, target_value]
            pen = pg.mkPen(color=(0, 200, 0, 200) if measure else (200, 0, 0, 200), width=2)
            self._preview.plot(x_vals, y_vals, pen=pen)
            current = target_value
            current_time += duration
        self._clear_current_marker()

    def _clear_current_marker(self) -> None:
        """Clear the current-point marker from the preview."""
        self._current_marker.setData(x=[], y=[])

    def _elapsed_time_for_segment_value(self, stage_index: int, value: float) -> float:
        """Estimate elapsed sweep time for *value* within the given segment."""
        if stage_index < 0:
            return 0.0
        current = self._generator.eval_float(self._generator.start)
        elapsed = 0.0
        target_value = float(value)
        for current_stage, (target, rate, _measure) in enumerate(self._generator.segments):
            target_value_for_segment = self._generator.eval_float(target)
            rate_magnitude = abs(self._generator.eval_float(rate))
            segment_distance = abs(target_value_for_segment - current)
            duration = (
                self._generator.duration_seconds_for_distance_rate(
                    segment_distance,
                    rate_magnitude,
                )
                if rate_magnitude > 0.0
                else 0.0
            )

            if current_stage == stage_index:
                if segment_distance > 0.0:
                    fraction = abs(target_value - current) / segment_distance
                    fraction = max(0.0, min(1.0, fraction))
                    return elapsed + (fraction * duration)
                return elapsed

            elapsed += duration
            current = target_value_for_segment

        if not self._generator.segments:
            return 0.0
        return elapsed

    def _on_current_point_changed(self, index: int, value: float, stage_index: int) -> None:
        """Move the current-point marker to *(elapsed_time, value)*."""
        if index < 0 or stage_index < 0:
            self._clear_current_marker()
            return
        elapsed_time = self._elapsed_time_for_segment_value(stage_index, float(value))
        self._current_marker.setData(x=[elapsed_time], y=[float(value)])

    def _on_start_changed(self, value: float | str) -> None:
        self._generator.start = value
        self._refresh_preview()

    def _on_poll_changed(self, value: float | str) -> None:
        self._generator.poll_seconds = value

    def _on_start_timeout_changed(self, value: float | str) -> None:
        self._generator.start_timeout_seconds = value
