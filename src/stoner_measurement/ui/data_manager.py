"""Non-modal window for inspecting and resaving completed trace data."""

from __future__ import annotations

import logging
import pathlib

from qtpy import QtCore, QtWidgets  # pylint: disable=no-name-in-module
from qtpy.QtCore import Qt  # pylint: disable=no-name-in-module

from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.plugins.command.save import SAVE_WRITERS, SaveCommand, SavePayload
from stoner_measurement.qt_compat import pyqtSignal, pyqtSlot
from stoner_measurement.ui.icons import make_data_manager_icon
from stoner_measurement.ui.theme import muted_label_stylesheet

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


class DataManagerWindow(QtWidgets.QWidget):
    """Inspect trace shapes and save selected traces in either supported format.

    The window listens for catalogue and namespace notifications from the
    sequence engine. File writing happens in the global Qt thread pool after a
    point-in-time payload has been copied from the live namespace, so saving
    does not pause or otherwise control sequence execution.
    """

    def __init__(
        self,
        engine: SequenceEngine,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setWindowTitle("Data Manager")
        self.setWindowIcon(make_data_manager_icon())
        self.resize(720, 480)

        self._engine = engine
        self._trace_items: dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._active_workers: set[_SaveWorker] = set()

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
        self._trace_tree.itemChanged.connect(self._update_save_buttons)

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
        self._btn_refresh = QtWidgets.QPushButton("Refresh", self)
        self._btn_refresh.clicked.connect(self.refresh_traces)

        self._save_buttons: dict[str, QtWidgets.QPushButton] = {}
        for format_id, writer_cls in SAVE_WRITERS.items():
            button = QtWidgets.QPushButton(
                f"Save as {writer_cls.label}\N{HORIZONTAL ELLIPSIS}", self
            )
            button.setObjectName(f"saveAs{format_id.title()}Button")
            available = writer_cls.available()
            button.setEnabled(available)
            if not available:
                button.setToolTip(writer_cls.unavailable_reason())
            button.clicked.connect(
                lambda checked=False, selected_format=format_id: self._save_selected(
                    selected_format
                )
            )
            self._save_buttons[format_id] = button

        self._status_label = QtWidgets.QLabel("Select one or more traces to save.", self)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(muted_label_stylesheet())

        self._btn_close = QtWidgets.QPushButton("Close", self)
        self._btn_close.setMinimumWidth(70)
        self._btn_close.clicked.connect(self.hide)

        selection_row = QtWidgets.QHBoxLayout()
        selection_row.addWidget(self._btn_select_all)
        selection_row.addWidget(self._btn_select_none)
        selection_row.addWidget(self._btn_refresh)
        selection_row.addStretch()

        save_row = QtWidgets.QHBoxLayout()
        save_row.addStretch()
        for button in self._save_buttons.values():
            save_row.addWidget(button)
        save_row.addWidget(self._btn_close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._empty_label)
        layout.addWidget(self._trace_tree, 1)
        layout.addLayout(selection_row)
        layout.addWidget(self._status_label)
        layout.addLayout(save_row)

        self._engine.traces_catalog_changed.connect(self._schedule_refresh)
        self._engine.namespace_updated.connect(self._schedule_refresh)
        self.refresh_traces()

    @property
    def selected_trace_keys(self) -> set[str]:
        """Return the catalogue keys currently selected for saving."""
        checked = Qt.CheckState.Checked
        return {key for key, item in self._trace_items.items() if item.checkState(0) == checked}

    @pyqtSlot()
    def show_and_raise(self) -> None:
        """Refresh, show, and bring the non-modal window to the front."""
        self.refresh_traces()
        self.show()
        self.raise_()
        self.activateWindow()

    @pyqtSlot()
    def _schedule_refresh(self, *_args) -> None:
        """Coalesce rapid engine notifications into one trace-table update."""
        self._refresh_timer.start()

    @pyqtSlot()
    def refresh_traces(self) -> None:
        """Refresh trace names, shapes, and column tooltips from the engine."""
        previous = {
            key: item.checkState(0) == Qt.CheckState.Checked
            for key, item in self._trace_items.items()
        }
        catalog = self._engine.traces_catalog

        self._trace_tree.blockSignals(True)
        try:
            self._trace_tree.clear()
            self._trace_items.clear()
            for key, expression in sorted(catalog.items(), key=lambda pair: pair[0].lower()):
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
        finally:
            self._trace_tree.blockSignals(False)

        has_traces = bool(self._trace_items)
        self._empty_label.setVisible(not has_traces)
        self._trace_tree.setVisible(has_traces)
        self._btn_select_all.setEnabled(has_traces)
        self._btn_select_none.setEnabled(has_traces)
        self._update_save_buttons()

    def _trace_summary(self, expression: str) -> tuple[str, str]:
        """Return a rows-by-columns summary and a detailed column tooltip."""
        try:
            trace_data = self._engine.evaluate_expression(expression)
            frame = trace_data.df
            names = trace_data.names or {}
            units = trace_data.units or {}
            columns = list(
                self._column_label(column, names=names, units=units) for column in frame.columns
            )
            return (
                f"{len(frame):,} \N{MULTIPLICATION SIGN} {len(columns)}",
                "Columns:\n" + "\n".join(columns),
            )
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            return "\N{EM DASH}", f"Trace data is not currently available: {exc}"

    @staticmethod
    def _column_label(column, *, names: dict, units: dict) -> str:
        label = names.get(column) or str(column)
        unit = units.get(column, "")
        return f"{label} ({unit})" if unit else label

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._trace_tree.blockSignals(True)
        try:
            for item in self._trace_items.values():
                item.setCheckState(0, state)
        finally:
            self._trace_tree.blockSignals(False)
        self._update_save_buttons()

    @pyqtSlot()
    def _update_save_buttons(self, *_args) -> None:
        has_selection = bool(self.selected_trace_keys)
        busy = bool(self._active_workers)
        for format_id, button in self._save_buttons.items():
            button.setEnabled(has_selection and not busy and SAVE_WRITERS[format_id].available())

    def _save_selected(self, format_id: str) -> None:
        selected = self.selected_trace_keys
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
        self._update_save_buttons()
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
        self._update_save_buttons()

    def _save_failed(self, worker: _SaveWorker, message: str) -> None:
        self._active_workers.discard(worker)
        self._status_label.setText(f"Save failed: {message}")
        self._update_save_buttons()
        QtWidgets.QMessageBox.warning(self, "Data Manager", message)
