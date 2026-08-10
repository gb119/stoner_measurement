"""Shared output-selection table for state scan and sweep configuration pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy.QtCore import QSize, Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
)

from stoner_measurement.qt_compat import pyqtSignal

if TYPE_CHECKING:
    from stoner_measurement.plugins.state.base import StatePlugin


OUTPUT_ROLE_CHOICES = ("-", "x", "d", "y", "e")


class OutputSelectionTable(QTableWidget):
    """Select catalogue outputs and optionally override their trace roles."""

    selection_changed = pyqtSignal(bool)

    def __init__(self, plugin: StatePlugin, parent=None) -> None:
        super().__init__(0, 3, parent)
        self._plugin = plugin
        self._sync_in_progress = False
        self._checks: dict[str, QCheckBox] = {}
        self._role_combos: dict[str, QComboBox] = {}
        self.setObjectName("stateOutputSelectionTable")
        self.setHorizontalHeaderLabels(["Include", "Output", "Role"])
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.refresh()

    @property
    def all_selected(self) -> bool:
        """Whether every currently listed catalogue output is selected."""
        return bool(self._checks) and all(check.isChecked() for check in self._checks.values())

    def refresh(self) -> None:
        """Rebuild the table from the current engine values catalogue."""
        self._sync_in_progress = True
        self.setRowCount(0)
        self._checks.clear()
        self._role_combos.clear()
        keys = sorted(str(key) for key in self._plugin.engine_namespace.get("_values", {}))
        selected = None if self._plugin.collect_outputs is None else set(self._plugin.collect_outputs)
        configured_roles = self._plugin.collect_output_roles
        inferred_roles = (
            self._plugin.inferred_output_roles(keys)
            if self._plugin.collect_outputs is None and not configured_roles
            else {}
        )
        for row, key in enumerate(keys):
            self.insertRow(row)
            check = QCheckBox(self)
            check.setObjectName(f"collectOutput:{key}")
            check.setChecked(selected is None or key in selected)
            check.stateChanged.connect(self._sync_plugin)
            self.setCellWidget(row, 0, check)

            name_item = QTableWidgetItem(key)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 1, name_item)

            role_combo = QComboBox(self)
            role_combo.setObjectName(f"collectOutputRole:{key}")
            role_combo.setProperty("output_key", key)
            role_combo.addItems(OUTPUT_ROLE_CHOICES)
            role_combo.setCurrentText(configured_roles.get(key, inferred_roles.get(key, "-")))
            role_combo.currentTextChanged.connect(
                lambda role, output_key=key: self._role_changed(output_key, role)
            )
            self.setCellWidget(row, 2, role_combo)
            self._checks[key] = check
            self._role_combos[key] = role_combo
        self._sync_in_progress = False
        self._sync_plugin()
        self._update_height_limit()

    def _update_height_limit(self) -> None:
        """Cap the table at the height required to show every output row."""
        self.resizeRowsToContents()
        content_height = self.horizontalHeader().height() + 2 * self.frameWidth()
        content_height += sum(self.rowHeight(row) for row in range(self.rowCount()))
        if self.horizontalScrollBar().isVisible():
            content_height += self.horizontalScrollBar().height()
        self._content_height = content_height
        self.setMaximumHeight(content_height)

    def sizeHint(self) -> QSize:
        """Prefer the height needed for all rows while remaining shrinkable."""
        hint = super().sizeHint()
        hint.setHeight(getattr(self, "_content_height", hint.height()))
        return hint

    def select_all_with_heuristics(self) -> None:
        """Select every output and display the plugin's automatically inferred roles."""
        self._sync_in_progress = True
        for check in self._checks.values():
            check.setChecked(True)
        inferred_roles = self._plugin.inferred_output_roles(list(self._role_combos))
        for key, combo in self._role_combos.items():
            combo.setCurrentText(inferred_roles.get(key, "-"))
        self._plugin.collect_outputs = None
        self._plugin.collect_output_roles = {
            key: combo.currentText() for key, combo in self._role_combos.items()
        }
        self._sync_in_progress = False
        self.selection_changed.emit(self.all_selected)

    def _role_changed(self, output_key: str, role: str) -> None:
        if self._sync_in_progress:
            return
        if role == "x":
            self._sync_in_progress = True
            for key, combo in self._role_combos.items():
                if key != output_key and combo.currentText() == "x":
                    combo.setCurrentText("-")
            self._sync_in_progress = False
        self._sync_plugin()

    def _sync_plugin(self) -> None:
        if self._sync_in_progress:
            return
        selected = [key for key, check in self._checks.items() if check.isChecked()]
        self._plugin.collect_outputs = None if len(selected) == len(self._checks) else selected
        self._plugin.collect_output_roles = {
            key: combo.currentText() for key, combo in self._role_combos.items()
        }
        self.selection_changed.emit(self.all_selected)
