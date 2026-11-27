"""Non-modal window for inspecting and resaving completed trace data."""

from __future__ import annotations

import logging
import pathlib

from qtpy import QtCore, QtWidgets  # pylint: disable=no-name-in-module
from qtpy.QtCore import Qt  # pylint: disable=no-name-in-module
from qtpy.QtGui import QAction

from stoner_measurement.core.chart_trace import ChartTrace
from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.core.trace_data import TraceData
from stoner_measurement.plugins.command.save import SAVE_WRITERS, SaveCommand, SavePayload
from stoner_measurement.qt_compat import pyqtSignal, pyqtSlot
from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget
from stoner_measurement.ui.icons import make_data_manager_icon
from stoner_measurement.ui.theme import muted_label_stylesheet
from stoner_measurement.ui.trace_plot_dialog import TracePlotDialog, trace_column_label

logger = logging.getLogger(__name__)

_REFRESH_DELAY_MS = 100
_DEFAULT_FILENAMES = {"tdi": "measurement.txt", "nexus": "measurement.nxs"}
_DEFAULT_EXTENSIONS = {"tdi": ".txt", "nexus": ".nxs"}


class _SaveWorkerSignals(QtCore.QObject):
    """Signals emitted by a background save worker."""

    succeeded = pyqtSignal(str, int)
    failed = pyqtSignal(str)


class _SaveWorker(QtCore.QRunnable):
    """Write one immutable save payload without occupying the GUI thread."""

    def __init__(
        self,
        *,
        destination: pathlib.Path,
        format_id: str,
        payload: SavePayload,
        trace_count: int,
    ) -> None:
        super().__init__()
        self.destination = destination
        self.format_id = format_id
        self.payload = payload
        self.trace_count = trace_count
        self.signals = _SaveWorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        """Write the payload and report success or failure."""
        try:
            writer_cls = SAVE_WRITERS[self.format_id]
            if not writer_cls.available():
                raise RuntimeError(writer_cls.unavailable_reason())
            writer_cls().write(dest=self.destination, payload=self.payload)
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            logger.exception("Background data export failed")
            self.signals.failed.emit(str(exc))
            return
        self.signals.succeeded.emit(str(self.destination), self.trace_count)


class _TraceTableModel(QtCore.QAbstractTableModel):
    """Expose a dataframe snapshot to Qt without allocating an item per cell."""

    def __init__(self, parent):
        super().__init__(parent)
        self._frame = None
        self._headers: tuple[str, ...] = ()

    def set_trace(self, trace: TraceData | None) -> None:
        frame = trace.df if trace is not None else None
        headers = (
            tuple(str(trace_column_label(trace, column)) for column in trace.columns)
            if trace is not None
            else ()
        )
        old_rows = self.rowCount()
        new_rows = len(frame) if frame is not None else 0
        if headers != self._headers:
            self.beginResetModel()
            self._frame, self._headers = frame, headers
            self.endResetModel()
            return
        if new_rows > old_rows:
            self.beginInsertRows(QtCore.QModelIndex(), old_rows, new_rows - 1)
        elif new_rows < old_rows:
            self.beginRemoveRows(QtCore.QModelIndex(), new_rows, old_rows - 1)
        self._frame = frame
        if new_rows > old_rows:
            self.endInsertRows()
        elif new_rows < old_rows:
            self.endRemoveRows()
        shared_rows = min(old_rows, new_rows)
        if shared_rows and headers:
            self.dataChanged.emit(self.index(0, 0), self.index(shared_rows - 1, len(headers) - 1))

    def rowCount(self, parent=QtCore.QModelIndex()):  # noqa: N802
        return len(self._frame) if not parent.isValid() and self._frame is not None else 0

    def columnCount(self, parent=QtCore.QModelIndex()):  # noqa: N802
        return len(self._headers) if not parent.isValid() else 0

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole and self._frame is not None:
            return str(self._frame.iat[index.row(), index.column()])
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._headers[section] if 0 <= section < len(self._headers) else None
        return str(section)


class _TracePage(QtWidgets.QWidget):
    """One catalogue trace and its latest inspected snapshot."""

    def __init__(self, key: str, parent):
        super().__init__(parent)
        self.key = key
        self.trace: TraceData | None = None

        self.summary = QtWidgets.QLabel(self)
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(muted_label_stylesheet())
        self.model = _TraceTableModel(self)
        table = QtWidgets.QTableView(self)
        table.setModel(self.model)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setMinimumSectionSize(80)
        table.horizontalHeader().setDefaultSectionSize(155)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(table, 1)

    def refresh(self, engine: SequenceEngine, expression: str) -> None:
        """Capture the current frame before exposing its cells to the table."""
        try:
            trace = engine.evaluate_expression(expression)
            self.trace = (
                trace.snapshot()
                if isinstance(trace, ChartTrace)
                else TraceData(
                    trace.df, column_roles=trace.column_roles, names=trace.names, units=trace.units
                )
            )
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            self.trace = None
            self.summary.setText(f"Trace data is unavailable: {exc}")
        else:
            rows, columns = self.trace.df.shape
            self.summary.setText(
                f"{rows:,} rows · {columns:,} columns" if rows else "No rows acquired."
            )
        self.model.set_trace(self.trace)


class DataManagerWindow(QtWidgets.QWidget):
    """Inspect and plot trace data or save snapshots in either export format.

    The window listens for catalogue and namespace notifications from the
    sequence engine. File writing happens in the global Qt thread pool after a
    point-in-time payload has been copied from the live namespace, so saving
    does not pause or otherwise control sequence execution.
    """

    trace_plotted = pyqtSignal(str)

    def __init__(
        self,
        engine: SequenceEngine,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Data Manager")
        self.setWindowIcon(make_data_manager_icon())
        self.resize(900, 520)

        self._engine = engine
        self._trace_items: dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._trace_pages: dict[str, _TracePage] = {}
        self._catalog: dict[str, str] = {}
        self._active_workers: set[_SaveWorker] = set()
        self._plot_dialog: TracePlotDialog | None = None

        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(_REFRESH_DELAY_MS)
        self._refresh_timer.timeout.connect(self.refresh_traces)

        self._trace_tree = QtWidgets.QTreeWidget(self)
        self._trace_tree.setObjectName("dataManagerTraceTree")
        self._trace_tree.setColumnCount(3)
        self._trace_tree.setHeaderLabels(["Save", "Trace", "Shape"])
        self._trace_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self._trace_tree.setRootIsDecorated(False)
        self._trace_tree.setAlternatingRowColors(True)
        self._trace_tree.header().setStretchLastSection(False)
        self._trace_tree.header().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self._trace_tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self._trace_tree.header().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self._trace_tree.itemChanged.connect(self._update_actions)

        self._empty_label = QtWidgets.QLabel(
            "No traces are currently available. Generate or run a sequence to populate the catalogue.",
            self,
        )
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(muted_label_stylesheet())

        self._btn_select_all = QtWidgets.QPushButton("Select All", self)
        self._btn_select_all.clicked.connect(lambda: self._set_all_checked(True))
        self._btn_select_none = QtWidgets.QPushButton("Select None", self)
        self._btn_select_none.clicked.connect(lambda: self._set_all_checked(False))
        self._status_label = QtWidgets.QLabel(self)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(muted_label_stylesheet())

        self._btn_close = QtWidgets.QPushButton("Close", self)
        self._btn_close.setMinimumWidth(70)
        self._btn_close.clicked.connect(self.hide)

        selection_row = QtWidgets.QHBoxLayout()
        selection_row.addWidget(self._btn_select_all)
        selection_row.addWidget(self._btn_select_none)
        selection_row.addStretch()

        self._tabs = FontAwareTabWidget(self)
        self._tabs.setObjectName("dataManagerTraceTabs")
        self._overview = QtWidgets.QWidget(self._tabs)
        overview_layout = QtWidgets.QVBoxLayout(self._overview)
        overview_layout.addWidget(self._empty_label)
        overview_layout.addWidget(self._trace_tree, 1)
        overview_layout.addLayout(selection_row)
        self._tabs.addTab(self._overview, "All Traces")
        self._tabs.currentChanged.connect(self._refresh_active_trace)

        self._save_actions: dict[str, QAction] = {}
        self._plot_action = QAction("Plot Trace…", self)
        self._plot_action.triggered.connect(self._configure_plot)
        self._clear_trace_action = QAction("Clear Trace…", self)
        self._clear_trace_action.triggered.connect(self._clear_trace)
        menu_bar, toolbar = self._build_actions()

        footer = QtWidgets.QHBoxLayout()
        footer.addWidget(self._status_label, 1)
        footer.addWidget(self._btn_close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setMenuBar(menu_bar)
        layout.addWidget(toolbar)
        layout.addWidget(self._tabs, 1)
        layout.addLayout(footer)

        self._engine.traces_catalog_changed.connect(self._schedule_refresh)
        self._engine.namespace_updated.connect(self._schedule_refresh)
        self.refresh_traces()

    def _build_actions(self):
        menu_bar = QtWidgets.QMenuBar(self)
        file_menu = menu_bar.addMenu("&File")
        trace_menu = menu_bar.addMenu("&Trace")
        toolbar = QtWidgets.QToolBar("Data Manager", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        for format_id, writer_cls in SAVE_WRITERS.items():
            action = QAction(f"Save as {writer_cls.label}…", self)
            if not writer_cls.available():
                action.setToolTip(writer_cls.unavailable_reason())
            action.triggered.connect(
                lambda _checked=False, selected_format=format_id: self._save_selected(
                    selected_format
                )
            )
            self._save_actions[format_id] = action
            file_menu.addAction(action)
            toolbar.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction("&Close", self.hide)

        refresh = QAction("Refresh", self)
        refresh.triggered.connect(self.refresh_traces)
        trace_menu.addAction(self._plot_action)
        trace_menu.addAction(self._clear_trace_action)
        trace_menu.addAction(refresh)
        toolbar.addSeparator()
        toolbar.addAction(self._plot_action)
        toolbar.addAction(refresh)
        return menu_bar, toolbar

    @property
    def selected_trace_keys(self) -> set[str]:
        """Return the catalogue keys currently selected for saving."""
        checked = Qt.CheckState.Checked
        return {key for key, item in self._trace_items.items() if item.checkState(0) == checked}

    @pyqtSlot()
    def show_and_raise(self) -> None:
        """Show the active plot dialog or bring the refreshed manager forward."""
        window = self._plot_dialog or self
        if window is self:
            self.refresh_traces()
        window.show()
        window.raise_()
        window.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Close an active plot dialog during application shutdown."""
        dialog = self._plot_dialog
        self._plot_dialog = None
        if dialog is not None:
            dialog.reject()
        super().closeEvent(event)

    @pyqtSlot()
    def _schedule_refresh(self, *_args) -> None:
        """Coalesce rapid engine notifications into one trace-table update."""
        if self.isVisible() and not self._refresh_timer.isActive():
            self._refresh_timer.start()

    @pyqtSlot()
    def refresh_traces(self) -> None:
        """Synchronise catalogue tabs and refresh the active dataframe."""
        catalog = self._engine.traces_catalog
        keys = sorted(catalog, key=lambda key: (key.casefold(), key))
        self._catalog = catalog
        with QtCore.QSignalBlocker(self._tabs):
            for key in self._trace_pages.keys() - catalog.keys():
                page = self._trace_pages.pop(key)
                self._tabs.removeTab(self._tabs.indexOf(page))
                page.deleteLater()
            for index, key in enumerate(keys, start=1):
                if key not in self._trace_pages:
                    page = _TracePage(key, self._tabs)
                    self._trace_pages[key] = page
                    self._tabs.insertTab(index, page, key.replace("&", "&&"))
                self._tabs.setTabToolTip(index, catalog[key])
        self._refresh_overview(keys)
        self._refresh_active_trace()

    def _refresh_overview(self, keys: list[str]) -> None:
        previous = {
            key: item.checkState(0) == Qt.CheckState.Checked
            for key, item in self._trace_items.items()
        }
        with QtCore.QSignalBlocker(self._trace_tree):
            self._trace_tree.clear()
            self._trace_items.clear()
            for key in keys:
                expression = self._catalog[key]
                shape, tooltip = self._trace_summary(expression)
                item = QtWidgets.QTreeWidgetItem(["", key, shape])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if previous.get(key, True) else Qt.CheckState.Unchecked,
                )
                item.setToolTip(1, expression)
                item.setToolTip(2, tooltip)
                self._trace_tree.addTopLevelItem(item)
                self._trace_items[key] = item
        has_traces = bool(self._trace_items)
        self._empty_label.setVisible(not has_traces)
        self._trace_tree.setVisible(has_traces)
        self._btn_select_all.setEnabled(has_traces)
        self._btn_select_none.setEnabled(has_traces)

    @pyqtSlot()
    def _refresh_active_trace(self) -> None:
        page = self._tabs.currentWidget()
        if isinstance(page, _TracePage):
            page.refresh(self._engine, self._catalog[page.key])
        self._update_actions()

    def _trace_summary(self, expression: str) -> tuple[str, str]:
        """Return a rows-by-columns summary and a detailed column tooltip."""
        try:
            trace_data = self._engine.evaluate_expression(expression)
            if isinstance(trace_data, TraceData):
                rows, keys = trace_data.row_count, trace_data.columns
            else:
                frame = trace_data.df
                rows, keys = len(frame), frame.columns
            columns = [str(trace_column_label(trace_data, column)) for column in keys]
            return (
                f"{rows:,} \N{MULTIPLICATION SIGN} {len(columns)}",
                "Columns:\n" + "\n".join(columns),
            )
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            return "\N{EM DASH}", f"Trace data is not currently available: {exc}"

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        with QtCore.QSignalBlocker(self._trace_tree):
            for item in self._trace_items.values():
                item.setCheckState(0, state)
        self._update_actions()

    def _save_keys(self) -> set[str]:
        page = self._tabs.currentWidget()
        if isinstance(page, _TracePage):
            return {page.key} if page.trace is not None and page.trace.row_count else set()
        return self.selected_trace_keys

    @pyqtSlot()
    def _update_actions(self) -> None:
        has_selection = bool(self._save_keys())
        busy = bool(self._active_workers)
        for format_id, action in self._save_actions.items():
            action.setEnabled(has_selection and not busy and SAVE_WRITERS[format_id].available())
        page = self._tabs.currentWidget()
        self._plot_action.setEnabled(
            isinstance(page, _TracePage) and has_selection and self._engine.plot_client is not None
        )
        self._clear_trace_action.setEnabled(
            isinstance(page, _TracePage)
            and has_selection
            and self._engine.chart_trace(page.key) is not None
        )

    @pyqtSlot()
    def _clear_trace(self) -> None:
        page = self._tabs.currentWidget()
        if not isinstance(page, _TracePage):
            return
        trace = self._engine.chart_trace(page.key)
        if trace is None:
            return
        buttons = QtWidgets.QMessageBox.StandardButton
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Clear Trace",
            f"Discard the recorded rows in {page.key!r}?",
            buttons.Yes | buttons.Cancel,
            buttons.Cancel,
        )
        if confirm == buttons.Yes:
            trace.clear()
            self._engine.notify_namespace_updated()
            self.refresh_traces()

    @pyqtSlot()
    def _configure_plot(self) -> None:
        if self._plot_dialog is not None:
            return
        page = self._tabs.currentWidget()
        if not isinstance(page, _TracePage) or page.trace is None or not page.trace.row_count:
            return
        dialog = TracePlotDialog(self._engine, page.key, page.trace, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.plotted.connect(self._on_trace_plotted)
        dialog.finished.connect(self._restore_after_plot)
        self._plot_dialog = dialog
        self.hide()
        self.show_and_raise()

    @pyqtSlot()
    def _restore_after_plot(self) -> None:
        if self._plot_dialog is not None:
            self._plot_dialog = None
            self.show_and_raise()

    @pyqtSlot(str)
    def _on_trace_plotted(self, title: str) -> None:
        self._status_label.setText(f"Plotted {title}.")
        self.trace_plotted.emit(title)

    def _save_selected(self, format_id: str) -> None:
        if self._active_workers:
            return
        selected = self._save_keys()
        if not selected:
            self._status_label.setText("Select at least one trace to save.")
            return

        destination = self._choose_destination(format_id)
        if destination is None:
            return

        try:
            command = SaveCommand()
            command.sequence_engine = self._engine
            payload = command.build_payload(trace_keys=selected)
            if not payload.columns:
                raise RuntimeError(
                    "None of the selected traces currently contains accessible data."
                )
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            logger.exception("Could not snapshot selected traces")
            self._status_label.setText(f"Save failed: {exc}")
            QtWidgets.QMessageBox.warning(self, "Data Manager", str(exc))
            return

        worker = _SaveWorker(
            destination=destination,
            format_id=format_id,
            payload=payload,
            trace_count=len(selected),
        )
        self._active_workers.add(worker)
        worker.signals.succeeded.connect(
            lambda path, count, current=worker: self._save_succeeded(current, path, count)
        )
        worker.signals.failed.connect(
            lambda message, current=worker: self._save_failed(current, message)
        )
        activity = " while the sequence continues" if self._engine.is_running else ""
        self._status_label.setText(f"Saving snapshot{activity}\N{HORIZONTAL ELLIPSIS}")
        self._update_actions()
        QtCore.QThreadPool.globalInstance().start(worker)

    def _choose_destination(self, format_id: str) -> pathlib.Path | None:
        from stoner_measurement.app_config import default_data_directory

        writer_cls = SAVE_WRITERS[format_id]
        base_dir = pathlib.Path(default_data_directory() or pathlib.Path.cwd())
        suggested = base_dir / _DEFAULT_FILENAMES[format_id]
        filename, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            f"Save selected traces as {writer_cls.label}",
            str(suggested),
            writer_cls.file_filter,
        )
        if not filename:
            return None
        destination = pathlib.Path(filename)
        if not destination.suffix:
            destination = destination.with_suffix(_DEFAULT_EXTENSIONS[format_id])
        return destination

    def _save_succeeded(self, worker: _SaveWorker, path: str, trace_count: int) -> None:
        self._active_workers.discard(worker)
        noun = "trace" if trace_count == 1 else "traces"
        self._status_label.setText(f"Saved {trace_count} {noun} to {path}")
        logger.info("Data Manager saved %d %s to %s", trace_count, noun, path)
        self._update_actions()

    def _save_failed(self, worker: _SaveWorker, message: str) -> None:
        self._active_workers.discard(worker)
        self._status_label.setText(f"Save failed: {message}")
        self._update_actions()
        QtWidgets.QMessageBox.warning(self, "Data Manager", message)
