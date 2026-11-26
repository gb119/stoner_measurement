"""Interactive XY plotting of an acquired trace snapshot."""

from __future__ import annotations

from uuid import uuid4

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from stoner_measurement.core.plotting.contracts import PlotRequest, ResultStatus
from stoner_measurement.core.plotting.producers import xy_update
from stoner_measurement.core.trace_data import (
    COLUMN_ROLE_D,
    COLUMN_ROLE_E,
    COLUMN_ROLE_X,
    COLUMN_ROLE_Y,
    TraceData,
)
from stoner_measurement.plugins.command.plot_forms import axis_names, refresh_axis_combo
from stoner_measurement.qt_compat import pyqtSignal, pyqtSlot
from stoner_measurement.ui.axis_mappings import AxisLabel
from stoner_measurement.ui.trace_plot_style import (
    TracePlotStyle,
    add_trace_style_controls,
    trace_style_dict,
)


def trace_column_label(trace: TraceData, column: str) -> AxisLabel:
    """Return a column's display name and physical unit."""
    return AxisLabel(trace.names.get(column) or str(column), trace.units.get(column, ""))


class TracePlotDialog(QDialog):
    """Configure and add multiple XY plots from one trace snapshot."""

    plotted = pyqtSignal(str)

    def __init__(self, engine, key: str, trace: TraceData, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Plot Trace — {key}")
        self._engine = engine
        self._key = key
        self._trace = trace
        self._style = TracePlotStyle()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self._x_channel = self._channel_combo("xChannel", COLUMN_ROLE_X)
        self._y_channel = self._channel_combo("yChannel", COLUMN_ROLE_Y)
        if not trace.get_columns_by_role(COLUMN_ROLE_Y) and self._y_channel.count() > 1:
            self._y_channel.setCurrentIndex(int(self._x_channel.currentIndex() == 0))
        form.addRow("X data:", self._x_channel)
        form.addRow("Y data:", self._y_channel)

        self._title = QLineEdit(self)
        self._title.setClearButtonEnabled(True)
        form.addRow("Title:", self._title)
        self._x_channel.currentIndexChanged.connect(self._update_default_title)
        self._y_channel.currentIndexChanged.connect(self._update_default_title)
        self._update_default_title()

        self._x_axis = QComboBox(self)
        self._y_axis = QComboBox(self)
        x_axes, y_axes = axis_names(engine)
        refresh_axis_combo(self._x_axis, x_axes, "bottom" if "bottom" in x_axes else x_axes[0])
        refresh_axis_combo(self._y_axis, y_axes, "left" if "left" in y_axes else y_axes[0])
        form.addRow("X axis:", self._x_axis)
        form.addRow("Y axis:", self._y_axis)
        add_trace_style_controls(form, self._style)

        self._status = QLabel(self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        send = buttons.addButton("Send to Plot Window", QDialogButtonBox.ButtonRole.ActionRole)
        send.setDefault(True)
        send.clicked.connect(self._send_plot)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _channel_combo(self, name: str, role: str) -> QComboBox:
        combo = QComboBox(self)
        combo.setObjectName(name)
        for column in self._trace.columns:
            combo.addItem(str(trace_column_label(self._trace, column)), column)
            combo.setItemData(combo.count() - 1, str(column), Qt.ItemDataRole.ToolTipRole)
        preferred = self._trace.get_columns_by_role(role)
        if preferred:
            combo.setCurrentIndex(combo.findData(preferred[0]))
        return combo

    @pyqtSlot()
    def _update_default_title(self) -> None:
        x_label = trace_column_label(self._trace, self._x_channel.currentData())
        y_label = trace_column_label(self._trace, self._y_channel.currentData())
        self._title.setPlaceholderText(f"{self._key}: {y_label.label} vs {x_label.label}")

    def _uncertainty(self, column):
        """Follow the selected channel's uncertainty even when axes are swapped."""
        for data_role, error_role in (
            (COLUMN_ROLE_X, COLUMN_ROLE_D),
            (COLUMN_ROLE_Y, COLUMN_ROLE_E),
        ):
            columns = self._trace.get_columns_by_role(data_role)
            errors = self._trace.get_columns_by_role(error_role)
            if column in columns and (index := columns.index(column)) < len(errors):
                return self._trace.df[errors[index]].to_numpy(dtype=float)
        return None

    @pyqtSlot()
    def _send_plot(self) -> None:
        title = self._title.text().strip() or self._title.placeholderText()
        try:
            client = self._engine.plot_client
            if client is None:
                raise RuntimeError("The main plot display is unavailable.")
            x_column = self._x_channel.currentData()
            y_column = self._y_channel.currentData()
            frame = self._trace.df
            request = PlotRequest(
                xy_update(
                    uuid4().hex,
                    frame[x_column].to_numpy(dtype=float),
                    frame[y_column].to_numpy(dtype=float),
                    x_error=self._uncertainty(x_column),
                    y_error=self._uncertainty(y_column),
                    x_label=trace_column_label(self._trace, x_column),
                    y_label=trace_column_label(self._trace, y_column),
                    x_axis=self._x_axis.currentText(),
                    y_axis=self._y_axis.currentText(),
                    style=trace_style_dict(self._style),
                    title=title,
                )
            )
            result = client.apply_now(request).wait(0)
            if result is None or result.status != ResultStatus.APPLIED:
                raise RuntimeError(
                    (result.message if result else "") or "The plot could not be displayed."
                )
        except (TypeError, ValueError, RuntimeError) as exc:
            self._status.setText(f"Plot failed: {exc}")
            return
        self._status.setText(f"Plotted {title}.")
        self.plotted.emit(title)
