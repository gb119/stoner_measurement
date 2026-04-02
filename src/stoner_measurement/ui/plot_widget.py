"""Central PyQtGraph plotting widget — middle 50 % of the main window."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from stoner_measurement.core.runner import SequenceRunner


class PlotWidget(QWidget):
    """PyQtGraph-based plot area for displaying measurement data.

    Parameters
    ----------
    runner:
        The application :class:`~stoner_measurement.core.runner.SequenceRunner`
        whose ``data_ready`` signal is connected to :meth:`append_data`.
    parent:
        Optional Qt parent widget.
    """

    def __init__(
        self,
        runner: SequenceRunner,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner

        # Storage for plotted data
        self._x_data: list[float] = []
        self._y_data: list[float] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create the pyqtgraph plot widget
        self._pg_widget = pg.PlotWidget()
        self._pg_widget.setObjectName("pgPlotWidget")
        self._pg_widget.setBackground("w")
        self._pg_widget.showGrid(x=True, y=True, alpha=0.3)
        self._pg_widget.setLabel("left", "Value")
        self._pg_widget.setLabel("bottom", "Step")

        self._curve = self._pg_widget.plot(pen=pg.mkPen(color="b", width=2))

        layout.addWidget(self._pg_widget)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append_data(self, x: float, y: float) -> None:
        """Append a single (x, y) data point to the live plot.

        Parameters
        ----------
        x:
            Horizontal axis value.
        y:
            Vertical axis value.
        """
        self._x_data.append(x)
        self._y_data.append(y)
        self._curve.setData(
            np.array(self._x_data, dtype=float),
            np.array(self._y_data, dtype=float),
        )

    def clear_data(self) -> None:
        """Clear all plotted data."""
        self._x_data.clear()
        self._y_data.clear()
        self._curve.setData([], [])

    @property
    def x_data(self) -> list[float]:
        """Horizontal axis data."""
        return list(self._x_data)

    @property
    def y_data(self) -> list[float]:
        """Vertical axis data."""
        return list(self._y_data)

    @property
    def pg_widget(self) -> pg.PlotWidget:
        """The underlying :class:`pyqtgraph.PlotWidget`."""
        return self._pg_widget
