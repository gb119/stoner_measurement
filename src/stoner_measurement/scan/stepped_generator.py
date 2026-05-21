"""Stepped scan generator and its configuration widget.

:class:`SteppedScanGenerator` generates a sequence of values defined by a
start value and a series of stages, each specifying a target, step size,
number of steps, and measurement flag. :class:`SteppedScanWidget` provides a
tabbed Qt widget for editing the stage table and previewing the resulting
scan.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtGui
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.scan.base import BaseScanGenerator
from stoner_measurement.ui.widgets import SISpinBox

_SPINBOX_MAX_ABS = 1e9
_MIN_STEP = 0.0
_DEFAULT_TARGET = 1.0
_DEFAULT_STEP = 0.1
_DEFAULT_NUM_STEPS = 10
_MIN_NUM_STEPS = 1
_MAX_NUM_STEPS = 10_000


class SteppedScanGenerator(BaseScanGenerator):
    """Scan generator that builds a sequence from a series of target–step stages.

    The sequence begins at *start* and advances through each stage in order.
    Within each stage the scan moves from the current position to *target* in
    *num_steps* equal increments.  The displayed step size is derived from the
    current position, target, and number of steps, and is therefore adjusted
    automatically when the number of steps is capped or edited.  Zero-distance
    stages are treated as holds and contribute repeated points at the current
    value.

    Each stage carries a *measure* flag.  When ``True`` all points in that
    stage are recorded as measurements; when ``False`` they are positioning
    moves only.  The initial *start* point inherits the *measure* flag from
    the first stage (or ``True`` when there are no stages).

    Attributes:
        start (float):
            Initial value from which the first stage begins.
        stages (list[tuple[float, float, int, bool]]):
            Ordered list of ``(target, step_size, num_steps, measure)`` stage
            definitions.

    Keyword Parameters:
        start (float):
            Initial scan value. Defaults to ``0.0``.
        stages (list[tuple[float, float, bool] | tuple[float, float, int, bool]] | None):
            Initial stage list. Legacy ``(target, step_size, measure)`` tuples
            are accepted and converted to the canonical four-field form.
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.25, True)])
        >>> gen.generate().tolist()
        [0.0, 0.25, 0.5, 0.75, 1.0]
        >>> gen.measure_flags().tolist()
        [True, True, True, True, True]
    """

    def __init__(
        self,
        *,
        start: float = 0.0,
        stages: list[tuple[float, float, bool] | tuple[float, float, int, bool]] | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialise the stepped scan generator."""
        super().__init__(parent)
        self._start = float(start)
        self._stages: list[tuple[float, int, bool]] = []
        if stages:
            self.stages = stages  # use setter for validation

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def start(self) -> float:
        """Initial scan value."""
        return self._start

    @start.setter
    def start(self, value: float) -> None:
        self._start = float(value)
        self._invalidate_cache()

    @property
    def stages(self) -> list[tuple[float, float, int, bool]]:
        """Ordered list of ``(target, step_size, num_steps, measure)`` stage definitions."""
        result: list[tuple[float, float, int, bool]] = []
        current = self._start
        for target, num_steps, measure in self._stages:
            result.append(
                (target, self._step_size_for_stage(current, target, num_steps), num_steps, measure)
            )
            current = target
        return result

    @stages.setter
    def stages(
        self,
        value: list[tuple[float, float, bool] | tuple[float, float, int, bool]],
    ) -> None:
        stages: list[tuple[float, int, bool]] = []
        current = self._start
        for i, stage in enumerate(value):
            if len(stage) == 3:
                target, step, measure = stage
                step_value = float(step)
                if step_value < 0:
                    raise ValueError(f"Step size must be non-negative; stage {i} has step={step!r}.")
                target_value = float(target)
                num_steps = self._step_count_from_step_size(current, target_value, step_value)
                stages.append((target_value, num_steps, bool(measure)))
                current = target_value
                continue
            if len(stage) != 4:
                raise ValueError(
                    "Each stage must be a (target, step_size, measure) or "
                    "(target, step_size, num_steps, measure) tuple."
                )
            target, step, num_steps, measure = stage
            step_value = float(step)
            if step_value < 0:
                raise ValueError(f"Step size must be non-negative; stage {i} has step={step!r}.")
            target_value = float(target)
            stages.append((target_value, self._normalise_step_count(num_steps), bool(measure)))
            current = target_value
        self._stages = stages
        self._invalidate_cache()

    @staticmethod
    def _normalise_step_count(value: float | int) -> int:
        """Clamp a step count to the supported range."""
        return max(_MIN_NUM_STEPS, min(_MAX_NUM_STEPS, int(round(float(value)))))

    @classmethod
    def _step_count_from_step_size(cls, current: float, target: float, step_size: float) -> int:
        """Derive a bounded step count from *step_size*."""
        distance = abs(target - current)
        if distance == 0.0:
            return _MIN_NUM_STEPS
        if step_size == 0.0:
            return _MAX_NUM_STEPS
        return cls._normalise_step_count(distance / step_size)

    @staticmethod
    def _step_size_for_stage(current: float, target: float, num_steps: int) -> float:
        """Return the canonical step size for a stage."""
        distance = abs(target - current)
        if distance == 0.0:
            return 0.0
        return distance / num_steps

    # ------------------------------------------------------------------
    # Core computation helpers
    # ------------------------------------------------------------------

    def _stage_points(self) -> list[tuple[np.ndarray, bool, int]]:
        """Compute per-stage scan point arrays."""
        result: list[tuple[np.ndarray, bool, int]] = []
        current = self._start
        for stage_index, (target, num_steps, measure) in enumerate(self._stages):
            distance = abs(target - current)
            if distance == 0.0:
                pts = np.full(num_steps, current, dtype=float)
            else:
                pts = np.linspace(current, target, num_steps + 1)[1:]
            result.append((pts, measure, stage_index))
            current = float(target)
        return result

    # ------------------------------------------------------------------
    # BaseScanGenerator interface
    # ------------------------------------------------------------------

    def generate(self) -> np.ndarray:
        """Compute the stepped scan sequence.

        Returns:
            (np.ndarray):
                A 1-D float array beginning at *start* and advancing through
                each stage.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
            >>> gen.generate().tolist()
            [0.0, 0.5, 1.0]
        """
        stage_data = self._stage_points()
        if not stage_data:
            return np.array([self._start], dtype=float)
        arrays = [np.array([self._start], dtype=float)] + [pts for pts, _, _ in stage_data]
        return np.concatenate(arrays)

    def measure_flags(self) -> np.ndarray:
        """Return per-point measure flags for the stepped sequence.

        The start point inherits the measure flag of the first stage.  When
        there are no stages the single start-point flag is ``True``.

        Returns:
            (np.ndarray):
                A 1-D boolean array of the same length as :meth:`generate`.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = SteppedScanGenerator(
            ...     start=0.0,
            ...     stages=[(1.0, 0.5, True), (2.0, 0.5, False)],
            ... )
            >>> gen.measure_flags().tolist()
            [True, True, True, False, False]
        """
        stage_data = self._stage_points()
        if not stage_data:
            return np.array([True], dtype=bool)
        start_flag = stage_data[0][1]
        per_stage_flags = np.repeat(
            [m for _, m, _ in stage_data],
            [len(pts) for pts, _, _ in stage_data],
        )
        return np.concatenate([[start_flag], per_stage_flags])

    def stage_indices(self) -> np.ndarray:
        """Return per-point stage indices for the stepped sequence."""
        stage_data = self._stage_points()
        if not stage_data:
            return np.array([0], dtype=int)
        per_stage_indices = np.repeat(
            [stage_index for _, _, stage_index in stage_data],
            [len(pts) for pts, _, _ in stage_data],
        )
        return np.concatenate([[0], per_stage_indices]).astype(int, copy=False)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a :class:`SteppedScanWidget` configured for this generator.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                A :class:`SteppedScanWidget` bound to this generator.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = SteppedScanGenerator()
            >>> widget = gen.config_widget()
            >>> widget is not None
            True
        """
        return SteppedScanWidget(generator=self, parent=parent)

    def to_json(self) -> dict:
        """Serialise this generator's configuration to a JSON-compatible dict.

        Returns:
            (dict):
                A dict with keys ``"type"``, ``"start"``, and ``"stages"``.
                Each element of ``"stages"`` is a
                ``[target, step_size, num_steps, measure]`` list suitable for
                direct JSON serialisation.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.25, True)])
            >>> d = gen.to_json()
            >>> d["type"]
            'SteppedScanGenerator'
            >>> d["start"]
            0.0
            >>> d["stages"]
            [[1.0, 0.25, 4, True]]
        """
        return {
            "type": "SteppedScanGenerator",
            "start": self._start,
            "stages": [list(stage) for stage in self.stages],
            "units": self._units,
        }

    @classmethod
    def _from_json_data(cls, data: dict, parent=None) -> SteppedScanGenerator:
        """Reconstruct a :class:`SteppedScanGenerator` from serialised *data*.

        Args:
            data (dict):
                Dict as produced by :meth:`to_json`.

        Keyword Parameters:
            parent (QObject | None):
                Optional Qt parent object.

        Returns:
            (SteppedScanGenerator):
                A fully configured instance.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = SteppedScanGenerator(start=2.0, stages=[(4.0, 1.0, False)])
            >>> restored = SteppedScanGenerator._from_json_data(gen.to_json())
            >>> restored.start
            2.0
            >>> restored.stages
            [(4.0, 1.0, 2, False)]
        """
        instance = cls(
            start=float(data.get("start", 0.0)),
            stages=[tuple(stage) for stage in data.get("stages", [])],
            parent=parent,
        )
        instance.units = str(data.get("units", ""))
        return instance


class SteppedScanWidget(QWidget):
    """Configuration and live-preview widget for :class:`SteppedScanGenerator`.

    The widget provides two tabs:

    * **Stages** — a :class:`~pyqtgraph.SpinBox` for the start value and a
      :class:`QTableWidget` where each row defines one stage (target, step
      size, number of steps, measure flag).  Rows can be added or removed with
      buttons below the table.
    * **Preview** — a scatter plot showing scan points coloured green
      (``measure=True``) or red (``measure=False``).

    Args:
        generator (SteppedScanGenerator):
            The generator instance to configure and preview.

    Keyword Parameters:
        parent (QWidget | None):
            Optional Qt parent widget.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> gen = SteppedScanGenerator()
        >>> widget = SteppedScanWidget(generator=gen)
        >>> widget.get_generator() is gen
        True
    """

    def __init__(
        self,
        generator: SteppedScanGenerator,
        parent: QWidget | None = None,
    ) -> None:
        """Initialise the widget and bind it to *generator*."""
        super().__init__(parent)
        self._generator = generator
        self._updating = False
        self._build_ui()
        self._connect_signals()
        self._refresh_plot()

    def _build_ui(self) -> None:
        """Build the tab widget with Stages and Preview tabs."""
        root_layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        root_layout.addWidget(self._tabs)

        # --- Stages tab ---
        stages_widget = QWidget()
        stages_layout = QVBoxLayout(stages_widget)

        start_form = QFormLayout()
        self._start_spin = SISpinBox()
        self._start_spin.setOpts(bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), step=0.1, decimals=4, siPrefix=True)
        self._start_spin.setValue(self._generator.start)
        self._start_spin.setToolTip("Initial scan value")
        start_form.addRow("Start:", self._start_spin)
        stages_layout.addLayout(start_form)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Target", "Step Size", "Steps", "Measure"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        stages_layout.addWidget(self._table)

        btn_layout = QHBoxLayout()
        self._add_btn = QPushButton("Add Stage")
        self._remove_btn = QPushButton("Remove Stage")
        btn_layout.addWidget(self._add_btn)
        btn_layout.addWidget(self._remove_btn)
        stages_layout.addLayout(btn_layout)

        self._tabs.addTab(stages_widget, "Stages")

        # --- Preview tab ---
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        # --- Preview plot ---
        self._plot_widget = pg.PlotWidget()

        font = QtGui.QFont()
        font.setPointSize(10)
        font.setBold(True)
        font.setFamily("Arial")

        axis_pen = pg.mkPen(color="white", width=2)
        for axis, label in zip(["left", "bottom"], ["Value", "Index"]):
            axis = self._plot_widget.getAxis(axis)
            axis.setTextPen(pg.mkPen("white"))
            axis.setTickFont(font)
            axis.setLabel(
                label, **{"font-size": "11pt", "font-family": "Arial", "font-weight": "bold", "color": "white"}
            )
            axis.setPen(axis_pen)
        self._green_scatter = pg.ScatterPlotItem(
            pen=None,
            brush=pg.mkBrush(color=(0, 200, 0, 200)),
            symbol="o",
            size=8,
        )
        self._red_scatter = pg.ScatterPlotItem(
            pen=None,
            brush=pg.mkBrush(color=(200, 0, 0, 200)),
            symbol="o",
            size=8,
        )
        self._current_marker = pg.ScatterPlotItem(
            pen=pg.mkPen(color=(255, 220, 0), width=2),
            brush=pg.mkBrush(0, 0, 0, 0),
            symbol="o",
            size=12,
        )
        self._plot_widget.addItem(self._green_scatter)
        self._plot_widget.addItem(self._red_scatter)
        self._plot_widget.addItem(self._current_marker)
        preview_layout.addWidget(self._plot_widget)
        self._tabs.addTab(preview_widget, "Preview")

        self.setLayout(root_layout)

        # Populate table from existing generator stages without triggering updates.
        self._updating = True
        try:
            for target, step, num_steps, measure in self._generator.stages:
                self._add_row(target, step, num_steps, measure, update=False)
        finally:
            self._updating = False

    def _connect_signals(self) -> None:
        """Wire control signals to parameter setters and plot refresh."""
        self._start_spin.valueChanged.connect(self._on_start_changed)
        self._add_btn.clicked.connect(self._add_default_row)
        self._remove_btn.clicked.connect(self._remove_selected_row)
        self._generator.values_changed.connect(self._refresh_plot)
        self._generator.current_point_changed.connect(self._on_current_point_changed)
        self._generator.units_changed.connect(self._update_units)
        self._update_units(self._generator.units)

    def _update_units(self, units: str) -> None:
        """Update the suffix of all value spinboxes to match *units*."""
        self._start_spin.setOpts(suffix=units)
        for row in range(self._table.rowCount()):
            target_w: SISpinBox | None = self._table.cellWidget(row, 0)
            step_w: SISpinBox | None = self._table.cellWidget(row, 1)
            if target_w is not None:
                target_w.setOpts(suffix=units)
            if step_w is not None:
                step_w.setOpts(suffix=units)

    def _add_row(
        self,
        target: float = _DEFAULT_TARGET,
        step: float = _DEFAULT_STEP,
        num_steps: int = _DEFAULT_NUM_STEPS,
        measure: bool = True,
        *,
        update: bool = True,
    ) -> None:
        """Insert a new stage row into the table."""
        self._updating = True
        try:
            row = self._table.rowCount()
            self._table.insertRow(row)

            target_spin = SISpinBox()
            target_spin.setOpts(
                bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), step=0.1, decimals=4,
                siPrefix=True, suffix=self._generator.units,
            )
            target_spin.setValue(float(target))
            target_spin.valueChanged.connect(self._on_table_changed)
            self._table.setCellWidget(row, 0, target_spin)

            step_spin = SISpinBox()
            step_spin.setOpts(
                bounds=(_MIN_STEP, _SPINBOX_MAX_ABS), step=0.1, decimals=4,
                siPrefix=True, suffix=self._generator.units,
            )
            step_spin.setValue(float(step))
            step_spin.valueChanged.connect(self._on_step_size_changed)
            self._table.setCellWidget(row, 1, step_spin)

            num_steps_spin = QSpinBox()
            num_steps_spin.setRange(_MIN_NUM_STEPS, _MAX_NUM_STEPS)
            num_steps_spin.setValue(int(num_steps))
            num_steps_spin.valueChanged.connect(self._on_table_changed)
            self._table.setCellWidget(row, 2, num_steps_spin)

            measure_cb = QCheckBox()
            measure_cb.setChecked(bool(measure))
            measure_cb.stateChanged.connect(self._on_table_changed)
            self._table.setCellWidget(row, 3, measure_cb)
        finally:
            self._updating = False
        if update:
            self._on_table_changed()

    def _add_default_row(self) -> None:
        """Add a new stage row with default target and step values."""
        self._add_row()

    def _remove_selected_row(self) -> None:
        """Remove the currently selected stage row from the table."""
        rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self._table.removeRow(row)
        self._on_table_changed()

    def _on_start_changed(self, value: float) -> None:
        """Update generator start value."""
        self._generator.start = value
        self._sync_table_to_generator()

    def _sender_row(self) -> int | None:
        """Return the table row containing the current sender widget."""
        sender = self.sender()
        if sender is None:
            return None
        for row in range(self._table.rowCount()):
            for column in range(self._table.columnCount()):
                if self._table.cellWidget(row, column) is sender:
                    return row
        return None

    def _stage_values_from_row(self, row: int) -> tuple[float, float, int, bool] | None:
        """Return the widget values for *row*."""
        target_w: SISpinBox | None = self._table.cellWidget(row, 0)
        step_w: SISpinBox | None = self._table.cellWidget(row, 1)
        num_steps_w: QSpinBox | None = self._table.cellWidget(row, 2)
        measure_cb: QCheckBox | None = self._table.cellWidget(row, 3)
        if target_w is None or step_w is None or num_steps_w is None or measure_cb is None:
            return None
        return target_w.value(), step_w.value(), num_steps_w.value(), measure_cb.isChecked()

    def _sync_table_to_generator(self) -> None:
        """Update the table widgets to the generator's canonical stage values."""
        stages = self._generator.stages
        self._updating = True
        try:
            while self._table.rowCount() < len(stages):
                self._add_row(update=False)
            while self._table.rowCount() > len(stages):
                self._table.removeRow(self._table.rowCount() - 1)
            for row, (target, step, num_steps, measure) in enumerate(stages):
                target_w: SISpinBox | None = self._table.cellWidget(row, 0)
                step_w: SISpinBox | None = self._table.cellWidget(row, 1)
                num_steps_w: QSpinBox | None = self._table.cellWidget(row, 2)
                measure_cb: QCheckBox | None = self._table.cellWidget(row, 3)
                if target_w is not None:
                    target_w.setValue(target)
                if step_w is not None:
                    step_w.setValue(step)
                if num_steps_w is not None:
                    num_steps_w.setValue(num_steps)
                if measure_cb is not None:
                    measure_cb.setChecked(measure)
        finally:
            self._updating = False

    def _update_generator_from_table(self, *, step_size_row: int | None = None) -> None:
        """Rebuild generator stages from the current table contents."""
        if self._updating:
            return
        stages: list[tuple[float, float, bool] | tuple[float, float, int, bool]] = []
        for row in range(self._table.rowCount()):
            values = self._stage_values_from_row(row)
            if values is None:
                continue
            target, step, num_steps, measure = values
            if row == step_size_row:
                stages.append((target, step, measure))
            else:
                stages.append((target, step, num_steps, measure))
        self._generator.stages = stages
        self._sync_table_to_generator()

    def _on_step_size_changed(self, *_args) -> None:
        """Update the edited row using its current step size."""
        self._update_generator_from_table(step_size_row=self._sender_row())

    def _on_table_changed(self, *_args) -> None:
        """Rebuild generator stages from the current table contents."""
        self._update_generator_from_table()

    def _refresh_plot(self) -> None:
        """Re-render the scatter plot from the current generator values."""
        values = self._generator.values
        flags = self._generator.flags
        indices = np.arange(len(values), dtype=float)
        green_mask = flags
        red_mask = ~flags
        if green_mask.any():
            self._green_scatter.setData(x=indices[green_mask], y=values[green_mask])
        else:
            self._green_scatter.setData(x=np.array([], dtype=float), y=np.array([], dtype=float))
        if red_mask.any():
            self._red_scatter.setData(x=indices[red_mask], y=values[red_mask])
        else:
            self._red_scatter.setData(x=np.array([], dtype=float), y=np.array([], dtype=float))
        self._clear_current_marker()

    def _clear_current_marker(self) -> None:
        """Clear the current-point marker from the preview."""
        self._current_marker.setData(x=np.array([], dtype=float), y=np.array([], dtype=float))

    def _on_current_point_changed(self, index: int, value: float) -> None:
        """Move the current-point marker to *(index, value)*."""
        self._current_marker.setData(x=np.array([float(index)]), y=np.array([float(value)]))

    def get_generator(self) -> SteppedScanGenerator:
        """Return the :class:`SteppedScanGenerator` bound to this widget.

        Returns:
            (SteppedScanGenerator):
                The generator instance being configured.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = SteppedScanGenerator()
            >>> widget = SteppedScanWidget(generator=gen)
            >>> widget.get_generator() is gen
            True
        """
        return self._generator
