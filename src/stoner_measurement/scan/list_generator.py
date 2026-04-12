"""List-based scan generator and its configuration widget.

:class:`ListScanGenerator` generates a sequence of values from an explicit
list of ``(target, measure)`` pairs.  Each target is visited in order as a
single step (no intermediate points are generated).
:class:`ListScanWidget` provides a tabbed Qt widget for editing the list and
previewing the resulting scan.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.scan.base import BaseScanGenerator

_SPINBOX_MAX_ABS = 1e9
_DEFAULT_TARGET = 1.0


class ListScanGenerator(BaseScanGenerator):
    """Scan generator that visits an explicit list of target values.

    Each entry in :attr:`stages` is a ``(target, measure)`` pair.  The
    generator jumps directly to each target in sequence — no intermediate
    points are produced.  The *measure* flag controls whether a given point
    is recorded as a measurement.

    Attributes:
        stages (list[tuple[float, bool]]):
            Ordered list of ``(target, measure)`` stage definitions.

    Keyword Parameters:
        stages (list[tuple[float, bool]] | None):
            Initial stage list.  Defaults to an empty list.
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> gen = ListScanGenerator(stages=[(0.0, True), (1.0, True), (2.0, False)])
        >>> gen.generate().tolist()
        [0.0, 1.0, 2.0]
        >>> gen.measure_flags().tolist()
        [True, True, False]
    """

    def __init__(
        self,
        *,
        stages: list[tuple[float, bool]] | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialise the list scan generator."""
        super().__init__(parent)
        self._stages: list[tuple[float, bool]] = []
        if stages:
            self.stages = stages

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def stages(self) -> list[tuple[float, bool]]:
        """Ordered list of ``(target, measure)`` stage definitions."""
        return list(self._stages)

    @stages.setter
    def stages(self, value: list[tuple[float, bool]]) -> None:
        self._stages = [(float(t), bool(m)) for t, m in value]
        self._invalidate_cache()

    # ------------------------------------------------------------------
    # BaseScanGenerator interface
    # ------------------------------------------------------------------

    def generate(self) -> np.ndarray:
        """Return the explicit list of target values.

        Returns:
            (np.ndarray):
                A 1-D float array containing each target value in order.
                Returns an empty array when :attr:`stages` is empty.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = ListScanGenerator(stages=[(1.0, True), (3.0, False)])
            >>> gen.generate().tolist()
            [1.0, 3.0]
        """
        if not self._stages:
            return np.array([], dtype=float)
        return np.array([t for t, _ in self._stages], dtype=float)

    def measure_flags(self) -> np.ndarray:
        """Return per-point measure flags for the list sequence.

        Returns:
            (np.ndarray):
                A 1-D boolean array of the same length as :meth:`generate`.
                Returns an empty array when :attr:`stages` is empty.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = ListScanGenerator(stages=[(1.0, True), (2.0, False), (3.0, True)])
            >>> gen.measure_flags().tolist()
            [True, False, True]
        """
        if not self._stages:
            return np.array([], dtype=bool)
        return np.array([m for _, m in self._stages], dtype=bool)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a :class:`ListScanWidget` configured for this generator.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                A :class:`ListScanWidget` bound to this generator.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = ListScanGenerator()
            >>> widget = gen.config_widget()
            >>> widget is not None
            True
        """
        return ListScanWidget(generator=self, parent=parent)

    def to_json(self) -> dict:
        """Serialise this generator's configuration to a JSON-compatible dict.

        Returns:
            (dict):
                A dict with keys ``"type"`` and ``"stages"``.  Each element
                of ``"stages"`` is a ``[target, measure]`` list suitable for
                direct JSON serialisation.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = ListScanGenerator(stages=[(1.0, True), (2.0, False)])
            >>> d = gen.to_json()
            >>> d["type"]
            'ListScanGenerator'
            >>> d["stages"]
            [[1.0, True], [2.0, False]]
        """
        return {
            "type": "ListScanGenerator",
            "stages": [[t, m] for t, m in self._stages],
        }

    @classmethod
    def _from_json_data(cls, data: dict, parent=None) -> ListScanGenerator:
        """Reconstruct a :class:`ListScanGenerator` from serialised *data*.

        Args:
            data (dict):
                Dict as produced by :meth:`to_json`.

        Keyword Parameters:
            parent (QObject | None):
                Optional Qt parent object.

        Returns:
            (ListScanGenerator):
                A fully configured instance.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = ListScanGenerator(stages=[(1.0, True), (3.0, False)])
            >>> restored = ListScanGenerator._from_json_data(gen.to_json())
            >>> restored.stages
            [(1.0, True), (3.0, False)]
        """
        stages = [(float(t), bool(m)) for t, m in data.get("stages", [])]
        return cls(stages=stages, parent=parent)


class ListScanWidget(QWidget):
    """Configuration and live-preview widget for :class:`ListScanGenerator`.

    The widget provides two tabs:

    * **Points** — a :class:`QTableWidget` where each row defines one point
      (target value and measure flag).  Rows can be added or removed with
      buttons below the table.
    * **Preview** — a scatter plot showing scan points coloured green
      (``measure=True``) or red (``measure=False``).

    Args:
        generator (ListScanGenerator):
            The generator instance to configure and preview.

    Keyword Parameters:
        parent (QWidget | None):
            Optional Qt parent widget.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> gen = ListScanGenerator()
        >>> widget = ListScanWidget(generator=gen)
        >>> widget.get_generator() is gen
        True
    """

    def __init__(
        self,
        generator: ListScanGenerator,
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
        """Build the tab widget with Points and Preview tabs."""
        root_layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        root_layout.addWidget(self._tabs)

        # --- Points tab ---
        points_widget = QWidget()
        points_layout = QVBoxLayout(points_widget)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Target", "Measure"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        points_layout.addWidget(self._table)

        btn_layout = QHBoxLayout()
        self._add_btn = QPushButton("Add Point")
        self._remove_btn = QPushButton("Remove Point")
        btn_layout.addWidget(self._add_btn)
        btn_layout.addWidget(self._remove_btn)
        points_layout.addLayout(btn_layout)

        self._tabs.addTab(points_widget, "Points")

        # --- Preview tab ---
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setLabel("bottom", "Point index")
        self._plot_widget.setLabel("left", "Value")
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
        self._plot_widget.addItem(self._green_scatter)
        self._plot_widget.addItem(self._red_scatter)
        preview_layout.addWidget(self._plot_widget)
        self._tabs.addTab(preview_widget, "Preview")

        self.setLayout(root_layout)

        # Populate table from existing generator stages without triggering updates.
        self._updating = True
        try:
            for target, measure in self._generator.stages:
                self._add_row(target, measure, update=False)
        finally:
            self._updating = False

    def _connect_signals(self) -> None:
        """Wire control signals to parameter setters and plot refresh."""
        self._add_btn.clicked.connect(self._add_default_row)
        self._remove_btn.clicked.connect(self._remove_selected_row)
        self._generator.values_changed.connect(self._refresh_plot)

    def _add_row(
        self,
        target: float = _DEFAULT_TARGET,
        measure: bool = True,
        *,
        update: bool = True,
    ) -> None:
        """Insert a new point row into the table."""
        self._updating = True
        try:
            row = self._table.rowCount()
            self._table.insertRow(row)

            target_spin = QDoubleSpinBox()
            target_spin.setRange(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS)
            target_spin.setSingleStep(0.1)
            target_spin.setDecimals(4)
            target_spin.setValue(float(target))
            target_spin.valueChanged.connect(self._on_table_changed)
            self._table.setCellWidget(row, 0, target_spin)

            measure_cb = QCheckBox()
            measure_cb.setChecked(bool(measure))
            measure_cb.stateChanged.connect(self._on_table_changed)
            self._table.setCellWidget(row, 1, measure_cb)
        finally:
            self._updating = False
        if update:
            self._on_table_changed()

    def _add_default_row(self) -> None:
        """Add a new point row with the default target value."""
        self._add_row()

    def _remove_selected_row(self) -> None:
        """Remove the currently selected point row from the table."""
        rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self._table.removeRow(row)
        self._on_table_changed()

    def _on_table_changed(self) -> None:
        """Rebuild generator stages from the current table contents."""
        if self._updating:
            return
        stages: list[tuple[float, bool]] = []
        for row in range(self._table.rowCount()):
            target_w: QDoubleSpinBox | None = self._table.cellWidget(row, 0)
            measure_cb: QCheckBox | None = self._table.cellWidget(row, 1)
            if target_w is None or measure_cb is None:
                continue
            stages.append((target_w.value(), measure_cb.isChecked()))
        self._generator.stages = stages

    def _refresh_plot(self) -> None:
        """Re-render the scatter plot from the current generator values."""
        values = self._generator.values
        flags = self._generator.flags
        if len(values) == 0:
            self._green_scatter.setData(x=np.array([], dtype=float), y=np.array([], dtype=float))
            self._red_scatter.setData(x=np.array([], dtype=float), y=np.array([], dtype=float))
            return
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

    def get_generator(self) -> ListScanGenerator:
        """Return the :class:`ListScanGenerator` bound to this widget.

        Returns:
            (ListScanGenerator):
                The generator instance being configured.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = ListScanGenerator()
            >>> widget = ListScanWidget(generator=gen)
            >>> widget.get_generator() is gen
            True
        """
        return self._generator
