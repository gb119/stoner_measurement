"""Monitor-and-filter sweep generator."""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from typing import Any

import pyqtgraph as pg
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.sweep.base import BaseSweepGenerator

_DEFAULT_POLL_SECONDS = 0.05


class MonitorAndFilterSweepGenerator(BaseSweepGenerator):
    """Set measure flags when monitored outputs change beyond configured thresholds."""

    def __init__(
        self,
        *,
        rows: list[tuple[str, bool, float]] | None = None,
        timeout: float = 1.0,
        termination_condition: str = "",
        poll_seconds: float = _DEFAULT_POLL_SECONDS,
        state_sweep=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(state_sweep=state_sweep, parent=parent)
        self._rows: list[tuple[str, bool, float]] = rows or [("", False, 0.0)]
        self._timeout = max(0.0, float(timeout))
        self._termination_condition = str(termination_condition)
        self._poll_seconds = max(0.0, float(poll_seconds))

    @property
    def rows(self) -> list[tuple[str, bool, float]]:
        return list(self._rows)

    @rows.setter
    def rows(self, value: list[tuple[str, bool, float]]) -> None:
        cleaned: list[tuple[str, bool, float]] = []
        for expr, as_percent, limit in value:
            cleaned.append((str(expr), bool(as_percent), float(limit)))
        self._rows = cleaned or [("", False, 0.0)]
        self._invalidate()

    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._timeout = max(0.0, float(value))
        self._invalidate()

    @property
    def termination_condition(self) -> str:
        return self._termination_condition

    @termination_condition.setter
    def termination_condition(self, value: str) -> None:
        self._termination_condition = str(value)
        self._invalidate()

    @property
    def poll_seconds(self) -> float:
        return self._poll_seconds

    @poll_seconds.setter
    def poll_seconds(self, value: float) -> None:
        self._poll_seconds = max(0.0, float(value))
        self._invalidate()

    def _eval_bool(self, expression: str) -> bool:
        plugin = self.state_sweep
        if plugin is None or not expression.strip():
            return False
        try:
            return bool(plugin.eval(expression))
        except (RuntimeError, SyntaxError, NameError, ValueError):
            return False

    def _resolve_expression(self, expression: str) -> str:
        plugin = self.state_sweep
        if plugin is None:
            return expression
        values_catalog = plugin.engine_namespace.get("_values", {})
        return str(values_catalog.get(expression, expression))

    def _eval_float(self, expression: str) -> float | None:
        plugin = self.state_sweep
        if plugin is None:
            return None
        if not expression.strip():
            return None
        resolved = self._resolve_expression(expression)
        try:
            return float(plugin.eval(resolved))
        except (RuntimeError, SyntaxError, NameError, ValueError, TypeError):
            return None

    def _change_exceeds_limit(self, current: float, baseline: float, use_percent: bool, limit: float) -> bool:
        if use_percent:
            if baseline == 0.0:
                delta = 0.0 if current == 0.0 else math.inf
            else:
                delta = abs((current - baseline) / baseline) * 100.0
        else:
            delta = abs(current - baseline)
        return delta >= limit

    def iter_points(self) -> Iterator[tuple[int, float, int, bool]]:
        plugin = self.state_sweep
        if plugin is None:
            return

        start_time = time.monotonic()
        last_measure_time = start_time
        baseline_values: list[float | None] = [None for _ in self._rows]

        while True:
            current_state = float(plugin.get_state())
            if self._eval_bool(self._termination_condition):
                return

            current_values: list[float | None] = [self._eval_float(expr) for expr, _use_percent, _limit in self._rows]

            triggered_index: int | None = None
            for idx, ((_, use_percent, limit), current, baseline) in enumerate(
                zip(self._rows, current_values, baseline_values, strict=True)
            ):
                if current is None or baseline is None:
                    continue
                if self._change_exceeds_limit(current, baseline, use_percent, float(limit)):
                    triggered_index = idx
                    break

            timeout_triggered = self._timeout <= 0.0 or (time.monotonic() - last_measure_time) >= self._timeout
            measure_flag = triggered_index is not None or timeout_triggered

            if measure_flag:
                baseline_values = current_values
                last_measure_time = time.monotonic()
            elif all(v is None for v in baseline_values):
                baseline_values = current_values

            yield (triggered_index if triggered_index is not None else -1), current_state, 0, measure_flag

            if self._poll_seconds > 0.0:
                time.sleep(self._poll_seconds)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        return MonitorAndFilterSweepWidget(generator=self, parent=parent)

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "MonitorAndFilterSweepGenerator",
            "rows": [[expr, use_percent, limit] for expr, use_percent, limit in self._rows],
            "timeout": self._timeout,
            "termination_condition": self._termination_condition,
            "poll_seconds": self._poll_seconds,
        }

    @classmethod
    def _from_json_data(cls, data: dict[str, Any], *, state_sweep=None, parent: QObject | None = None):
        rows = [(str(expr), bool(use_percent), float(limit)) for expr, use_percent, limit in data.get("rows", [])]
        return cls(
            rows=rows,
            timeout=float(data.get("timeout", 1.0)),
            termination_condition=str(data.get("termination_condition", "")),
            poll_seconds=float(data.get("poll_seconds", _DEFAULT_POLL_SECONDS)),
            state_sweep=state_sweep,
            parent=parent,
        )


class MonitorAndFilterSweepWidget(QWidget):
    """Configuration widget for MonitorAndFilterSweepGenerator."""

    def __init__(self, generator: MonitorAndFilterSweepGenerator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._generator = generator
        self._build_ui()
        self._populate_from_generator()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        form = QFormLayout()
        self._timeout_spin = pg.SpinBox()
        self._timeout_spin.setOpts(bounds=(0.0, 1e9), decimals=6, suffix="s")
        self._timeout_spin.valueChanged.connect(self._on_timeout_changed)
        form.addRow("Timeout:", self._timeout_spin)

        self._termination_edit = QLineEdit(self)
        self._termination_edit.editingFinished.connect(self._on_termination_changed)
        form.addRow("Termination condition:", self._termination_edit)
        root.addLayout(form)

        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["Parameter / expression", "Use %", "Limit"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._table)

        controls = QHBoxLayout()
        add_btn = QPushButton("Add Row", self)
        remove_btn = QPushButton("Remove Row", self)
        add_btn.clicked.connect(self._add_row)
        remove_btn.clicked.connect(self._remove_row)
        controls.addWidget(add_btn)
        controls.addWidget(remove_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        root.addWidget(QLabel("Measure flag is set by threshold crossing or timeout.", self))

    def _available_catalogue_keys(self) -> list[str]:
        plugin = self._generator.state_sweep
        if plugin is None:
            return []
        values_catalog = plugin.engine_namespace.get("_values", {})
        return sorted(str(k) for k in values_catalog)

    def _build_expression_combo(self, value: str) -> QComboBox:
        combo = QComboBox(self._table)
        combo.setEditable(True)
        for key in self._available_catalogue_keys():
            combo.addItem(key)
        combo.setCurrentText(value)
        combo.currentTextChanged.connect(self._sync_rows_from_table)
        return combo

    def _build_percent_checkbox(self, checked: bool) -> QCheckBox:
        check = QCheckBox(self._table)
        check.setChecked(checked)
        check.stateChanged.connect(self._sync_rows_from_table)
        return check

    def _build_limit_spin(self, value: float) -> pg.SpinBox:
        spin = pg.SpinBox(self._table)
        spin.setOpts(bounds=(0.0, 1e12), decimals=6)
        spin.setValue(float(value))
        spin.valueChanged.connect(self._sync_rows_from_table)
        return spin

    def _add_row(self) -> None:
        self._table.insertRow(self._table.rowCount())
        row = self._table.rowCount() - 1
        self._table.setCellWidget(row, 0, self._build_expression_combo(""))
        self._table.setCellWidget(row, 1, self._build_percent_checkbox(False))
        self._table.setCellWidget(row, 2, self._build_limit_spin(0.0))
        self._sync_rows_from_table()

    def _remove_row(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            row = self._table.rowCount() - 1
        if row >= 0:
            self._table.removeRow(row)
        if self._table.rowCount() == 0:
            self._add_row()
        self._sync_rows_from_table()

    def _populate_from_generator(self) -> None:
        self._timeout_spin.setValue(self._generator.timeout)
        self._termination_edit.setText(self._generator.termination_condition)
        self._table.setRowCount(0)
        for expression, use_percent, limit in self._generator.rows:
            self._table.insertRow(self._table.rowCount())
            row = self._table.rowCount() - 1
            self._table.setCellWidget(row, 0, self._build_expression_combo(expression))
            self._table.setCellWidget(row, 1, self._build_percent_checkbox(use_percent))
            self._table.setCellWidget(row, 2, self._build_limit_spin(limit))

    def _sync_rows_from_table(self) -> None:
        rows: list[tuple[str, bool, float]] = []
        for row in range(self._table.rowCount()):
            combo = self._table.cellWidget(row, 0)
            check = self._table.cellWidget(row, 1)
            spin = self._table.cellWidget(row, 2)
            expression = combo.currentText().strip() if isinstance(combo, QComboBox) else ""
            use_percent = check.isChecked() if isinstance(check, QCheckBox) else False
            limit = float(spin.value()) if isinstance(spin, pg.SpinBox) else 0.0
            rows.append((expression, use_percent, limit))
        self._generator.rows = rows

    def _on_timeout_changed(self, value: float) -> None:
        self._generator.timeout = float(value)

    def _on_termination_changed(self) -> None:
        self._generator.termination_condition = self._termination_edit.text().strip()
