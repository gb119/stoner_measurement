"""Settings dialogue for the Stoner Measurement application."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from qtpy.QtCore import QSettings, Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.app_config import (
    FEATURE_DEFINITIONS,
    KEY_CONSOLE_FONT_SIZE,
    KEY_DEFAULT_DATA_DIR,
    KEY_EDITOR_FONT_SIZE,
    KEY_FONT_SIZE,
    KEY_RIG,
    KEY_THEME,
    console_font_size_setting,
    default_data_directory,
    editor_font_size_setting,
    font_size_setting,
    load_app_config,
    rig_setting,
    save_app_config,
    set_app_config_value,
    theme_setting,
)
from stoner_measurement.resources import (
    install_predefined_sequence,
    install_toolbar_icon,
    load_plugin_catalogue_config,
    load_toolbar_config,
    save_plugin_catalogue_config,
    save_toolbar_config,
    user_config_root,
)
from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget
from stoner_measurement.ui.theme import DEFAULT_THEME, available_themes

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin

_ROW_TYPE_SEPARATOR = "__separator__"
_CATALOGUE_KIND_ROLE = Qt.ItemDataRole.UserRole
_CATALOGUE_GROUP = "group"
_CATALOGUE_PLUGIN = "plugin"


def make_app_settings() -> QSettings:
    """Return the QSettings store used for non-YAML UI state such as geometry."""
    return QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "University of Leeds",
        "Stoner Measurement",
    )


class SettingsDialog(QDialog):
    """Modal preferences dialogue for editing persistent application settings."""

    def __init__(
        self,
        parent: QWidget | None = None,
        available_plugins: Mapping[str, BasePlugin] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(620)

        self.toolbar_saved = False
        self.plugin_catalogue_saved = False
        self._toolbar_cfg = load_toolbar_config()
        self._plugin_catalogue_cfg = load_plugin_catalogue_config()
        self._available_plugins = dict(available_plugins or {})
        self._plugin_catalogue_dirty = False
        self._feature_checkboxes: dict[str, QCheckBox] = {}
        app_config = load_app_config()

        tabs = FontAwareTabWidget(self)
        tabs.addTab(self._build_general_tab(app_config), "General")
        tabs.addTab(self._build_features_tab(app_config), "Features")
        tabs.addTab(self._build_toolbar_tab(), "Toolbar")
        tabs.addTab(self._build_plugin_catalogue_tab(), "Plugin List")

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(tabs)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def _build_general_tab(self, app_config: dict) -> QWidget:
        tab = QWidget(self)
        form = QFormLayout(tab)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._data_dir_edit = QLineEdit(tab)
        self._data_dir_edit.setPlaceholderText("(none - use current working directory)")
        self._data_dir_edit.setText(default_data_directory(config=app_config))

        data_dir_browse = QPushButton("Browse...", tab)
        data_dir_browse.setMinimumWidth(80)
        data_dir_browse.clicked.connect(self._browse_data_dir)

        data_dir_row = QHBoxLayout()
        data_dir_row.setContentsMargins(0, 0, 0, 0)
        data_dir_row.addWidget(self._data_dir_edit)
        data_dir_row.addWidget(data_dir_browse)
        form.addRow("Default data directory:", data_dir_row)

        self._rig_edit = QLineEdit(tab)
        self._rig_edit.setPlaceholderText("Local measurement rig name")
        self._rig_edit.setText(rig_setting(config=app_config))
        self._rig_edit.setToolTip("Available to measurement scripts as details.rig.")
        form.addRow("Measurement rig:", self._rig_edit)

        self._theme_combo = QComboBox(tab)
        self._theme_combo.addItems([name.capitalize() for name in available_themes()])
        saved_theme = theme_setting(config=app_config) or DEFAULT_THEME
        index = max(0, available_themes().index(saved_theme) if saved_theme in available_themes() else 0)
        self._theme_combo.setCurrentIndex(index)
        form.addRow("Theme:", self._theme_combo)

        self._font_size_spin = QSpinBox(tab)
        self._font_size_spin.setRange(6, 48)
        self._font_size_spin.setSuffix(" pt")
        self._font_size_spin.setValue(font_size_setting(config=app_config))
        self._font_size_spin.setToolTip("Font size used by standard application widgets.")
        form.addRow("Application font size:", self._font_size_spin)

        self._editor_font_size_spin = QSpinBox(tab)
        self._editor_font_size_spin.setRange(6, 48)
        self._editor_font_size_spin.setSuffix(" pt")
        self._editor_font_size_spin.setValue(editor_font_size_setting(config=app_config))
        form.addRow("Code editor font size:", self._editor_font_size_spin)

        self._console_font_size_spin = QSpinBox(tab)
        self._console_font_size_spin.setRange(6, 48)
        self._console_font_size_spin.setSuffix(" pt")
        self._console_font_size_spin.setValue(console_font_size_setting(config=app_config))
        form.addRow("Console font size:", self._console_font_size_spin)
        return tab

    def _build_features_tab(self, app_config: dict) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        help_label = QLabel(
            "Disable a controller feature to hide its menu, toolbar, panel, status "
            "indicator, and any plugins that declare they depend on that controller.",
            tab,
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        for entry in FEATURE_DEFINITIONS:
            checkbox = QCheckBox(f"Enable {entry['label']}", tab)
            checkbox.setChecked(bool(app_config.get("features", {}).get(entry["key"], True)))
            self._feature_checkboxes[entry["key"]] = checkbox
            form.addRow(f"{entry['label']}:", checkbox)

        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    def _build_toolbar_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        self._toolbar_table = QTableWidget(0, 4, tab)
        self._toolbar_table.setHorizontalHeaderLabels(["Button name / separator", "Sequence", "Icon", "Tooltip"])
        self._toolbar_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._toolbar_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._toolbar_table.verticalHeader().setVisible(False)
        header = self._toolbar_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._toolbar_table.setMinimumHeight(220)
        self._load_toolbar_rows()
        layout.addWidget(self._toolbar_table)

        toolbar_help = QLabel(
            "Sequences are looked up by filename in the user and bundled sequences "
            "folders. Icons are looked up by filename in the user and bundled "
            "resources folders. Saving always writes a user toolbar.yaml override.",
            tab,
        )
        toolbar_help.setWordWrap(True)
        layout.addWidget(toolbar_help)

        toolbar_buttons_row = QHBoxLayout()
        toolbar_buttons_row.setContentsMargins(0, 0, 0, 0)
        add_toolbar_button = QPushButton("Add Button", tab)
        add_toolbar_button.clicked.connect(self._add_toolbar_row)
        add_separator_button = QPushButton("Add Separator", tab)
        add_separator_button.clicked.connect(self._add_separator_row)
        remove_toolbar_button = QPushButton("Remove Selected", tab)
        remove_toolbar_button.clicked.connect(self._remove_selected_toolbar_row)
        save_toolbar_button = QPushButton("Save Toolbar", tab)
        save_toolbar_button.clicked.connect(self._save_toolbar_from_ui)
        toolbar_buttons_row.addWidget(add_toolbar_button)
        toolbar_buttons_row.addWidget(add_separator_button)
        toolbar_buttons_row.addWidget(remove_toolbar_button)
        toolbar_buttons_row.addStretch(1)
        toolbar_buttons_row.addWidget(save_toolbar_button)
        layout.addLayout(toolbar_buttons_row)
        return tab

    def _build_plugin_catalogue_tab(self) -> QWidget:
        """Build the ordered functional-group editor for the plugin list."""
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        help_label = QLabel(
            "Group related sequence commands independently of their Python class. "
            "Groups may be nested to any depth. Add Group inserts beside the "
            "selection; Move In and Move Out change its nesting level. Plugins "
            "not listed here remain in their existing type categories.",
            tab,
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self._plugin_catalogue_tree = QTreeWidget(tab)
        self._plugin_catalogue_tree.setColumnCount(2)
        self._plugin_catalogue_tree.setHeaderLabels(
            ["Group / plugin entry point", "Display label"]
        )
        self._plugin_catalogue_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        header = self._plugin_catalogue_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._populate_plugin_catalogue_tree()
        self._plugin_catalogue_tree.itemChanged.connect(
            lambda *_args: self._mark_plugin_catalogue_dirty()
        )
        layout.addWidget(self._plugin_catalogue_tree)

        add_row = QHBoxLayout()
        self._plugin_catalogue_combo = QComboBox(tab)
        add_plugin = QPushButton("Add Plugin", tab)
        add_plugin.clicked.connect(self._add_catalogue_plugin)
        add_row.addWidget(self._plugin_catalogue_combo, 1)
        add_row.addWidget(add_plugin)
        layout.addLayout(add_row)

        buttons = QHBoxLayout()
        add_group = QPushButton("Add Group", tab)
        add_group.clicked.connect(self._add_catalogue_group)
        remove = QPushButton("Remove Selected", tab)
        remove.clicked.connect(self._remove_catalogue_item)
        move_up = QPushButton("Move Up", tab)
        move_up.clicked.connect(lambda: self._move_catalogue_item(-1))
        move_down = QPushButton("Move Down", tab)
        move_down.clicked.connect(lambda: self._move_catalogue_item(1))
        move_in = QPushButton("Move In", tab)
        move_in.clicked.connect(self._move_catalogue_item_in)
        move_out = QPushButton("Move Out", tab)
        move_out.clicked.connect(self._move_catalogue_item_out)
        save = QPushButton("Save Plugin List", tab)
        save.clicked.connect(self._save_plugin_catalogue_from_ui)
        for button in (add_group, remove, move_up, move_down, move_in, move_out):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        self._refresh_catalogue_plugin_combo()
        return tab

    def _populate_plugin_catalogue_tree(self) -> None:
        """Populate the plugin-list editor from the effective configuration."""
        self._plugin_catalogue_tree.blockSignals(True)
        try:
            self._populate_catalogue_items(
                self._plugin_catalogue_tree.invisibleRootItem(),
                self._plugin_catalogue_cfg.get("items", []),
            )
        finally:
            self._plugin_catalogue_tree.blockSignals(False)

    def _populate_catalogue_items(
        self, parent: QTreeWidgetItem, configured_items: list[dict]
    ) -> None:
        """Recursively append configured groups and plugins below *parent*."""
        for configured in configured_items:
            if "plugin" in configured:
                parent.addChild(
                    self._make_catalogue_item(
                        configured["plugin"],
                        configured.get("label", ""),
                        _CATALOGUE_PLUGIN,
                    )
                )
                continue
            group = self._make_catalogue_item(
                configured["group"], "", _CATALOGUE_GROUP
            )
            parent.addChild(group)
            self._populate_catalogue_items(group, configured.get("items", []))
            group.setExpanded(True)

    @staticmethod
    def _make_catalogue_item(
        name: str, label: str = "", kind: str = _CATALOGUE_GROUP
    ) -> QTreeWidgetItem:
        """Create one editable group or plugin row."""
        item = QTreeWidgetItem([name, label])
        item.setData(0, _CATALOGUE_KIND_ROLE, kind)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )
        return item

    def _catalogue_plugin_ids(self) -> set[str]:
        """Return entry-point names currently present in the editor."""
        result: set[str] = set()

        def collect(parent: QTreeWidgetItem) -> None:
            for index in range(parent.childCount()):
                item = parent.child(index)
                if item.data(0, _CATALOGUE_KIND_ROLE) == _CATALOGUE_PLUGIN:
                    plugin = item.text(0).strip()
                    if plugin:
                        result.add(plugin)
                else:
                    collect(item)

        collect(self._plugin_catalogue_tree.invisibleRootItem())
        return result

    def _refresh_catalogue_plugin_combo(self) -> None:
        """List available plugins that are not already grouped."""
        selected = self._plugin_catalogue_combo.currentData()
        grouped = self._catalogue_plugin_ids()
        self._plugin_catalogue_combo.clear()
        for ep_name, plugin in sorted(
            self._available_plugins.items(), key=lambda item: item[1].name.casefold()
        ):
            if ep_name not in grouped:
                self._plugin_catalogue_combo.addItem(
                    f"{plugin.name} ({ep_name})", ep_name
                )
        if selected:
            index = self._plugin_catalogue_combo.findData(selected)
            if index >= 0:
                self._plugin_catalogue_combo.setCurrentIndex(index)

    def _mark_plugin_catalogue_dirty(self) -> None:
        """Record that the plugin-list configuration has changed."""
        self._plugin_catalogue_dirty = True
        self._refresh_catalogue_plugin_combo()

    def _add_catalogue_group(self) -> None:
        """Insert a new group immediately after the selected node."""
        existing: set[str] = set()

        def collect_group_names(parent: QTreeWidgetItem) -> None:
            for index in range(parent.childCount()):
                child = parent.child(index)
                if child.data(0, _CATALOGUE_KIND_ROLE) == _CATALOGUE_GROUP:
                    existing.add(child.text(0))
                    collect_group_names(child)

        root = self._plugin_catalogue_tree.invisibleRootItem()
        collect_group_names(root)
        base = "New Group"
        name = base
        suffix = 2
        while name in existing:
            name = f"{base} {suffix}"
            suffix += 1
        item = self._make_catalogue_item(name, kind=_CATALOGUE_GROUP)
        selected = self._plugin_catalogue_tree.currentItem()
        if selected is None:
            root.addChild(item)
        else:
            parent = selected.parent() or root
            parent.insertChild(parent.indexOfChild(selected) + 1, item)
            if parent is not root:
                parent.setExpanded(True)
        self._plugin_catalogue_tree.setCurrentItem(item)
        self._plugin_catalogue_tree.editItem(item, 0)
        self._mark_plugin_catalogue_dirty()

    def _selected_catalogue_group(self) -> QTreeWidgetItem | None:
        """Return the selected item as a group, or its parent group."""
        selected = self._plugin_catalogue_tree.currentItem()
        if selected is None:
            return None
        if selected.data(0, _CATALOGUE_KIND_ROLE) == _CATALOGUE_GROUP:
            return selected
        parent = selected.parent()
        if (
            parent is not None
            and parent.data(0, _CATALOGUE_KIND_ROLE) == _CATALOGUE_GROUP
        ):
            return parent
        return None

    def _add_catalogue_plugin(self) -> None:
        """Append the selected ungrouped plugin to the selected group."""
        group = self._selected_catalogue_group()
        ep_name = self._plugin_catalogue_combo.currentData()
        if group is None or not ep_name:
            return
        plugin = self._available_plugins.get(ep_name)
        child = self._make_catalogue_item(
            ep_name,
            plugin.name if plugin is not None else "",
            _CATALOGUE_PLUGIN,
        )
        group.addChild(child)
        group.setExpanded(True)
        self._plugin_catalogue_tree.setCurrentItem(child)
        self._mark_plugin_catalogue_dirty()

    def _remove_catalogue_item(self) -> None:
        """Remove the selected plugin or functional group."""
        selected = self._plugin_catalogue_tree.currentItem()
        if selected is None:
            return
        parent = selected.parent()
        if parent is None:
            self._plugin_catalogue_tree.takeTopLevelItem(
                self._plugin_catalogue_tree.indexOfTopLevelItem(selected)
            )
        else:
            parent.takeChild(parent.indexOfChild(selected))
        self._mark_plugin_catalogue_dirty()

    def _move_catalogue_item(self, offset: int) -> None:
        """Move the selected group or plugin one position up or down."""
        selected = self._plugin_catalogue_tree.currentItem()
        if selected is None:
            return
        parent = selected.parent() or self._plugin_catalogue_tree.invisibleRootItem()
        current = parent.indexOfChild(selected)
        target = current + offset
        if not 0 <= target < parent.childCount():
            return
        was_expanded = selected.isExpanded()
        item = parent.takeChild(current)
        parent.insertChild(target, item)
        item.setExpanded(was_expanded)
        self._plugin_catalogue_tree.setCurrentItem(item)
        self._mark_plugin_catalogue_dirty()

    def _move_catalogue_item_in(self) -> None:
        """Make the selected node the last child of its preceding sibling group."""
        selected = self._plugin_catalogue_tree.currentItem()
        if selected is None:
            return
        root = self._plugin_catalogue_tree.invisibleRootItem()
        parent = selected.parent() or root
        index = parent.indexOfChild(selected)
        if index <= 0:
            return
        preceding = parent.child(index - 1)
        if preceding.data(0, _CATALOGUE_KIND_ROLE) != _CATALOGUE_GROUP:
            return
        was_expanded = selected.isExpanded()
        item = parent.takeChild(index)
        preceding.addChild(item)
        item.setExpanded(was_expanded)
        preceding.setExpanded(True)
        self._plugin_catalogue_tree.setCurrentItem(item)
        self._mark_plugin_catalogue_dirty()

    def _move_catalogue_item_out(self) -> None:
        """Promote the selected node to immediately after its parent group."""
        selected = self._plugin_catalogue_tree.currentItem()
        if selected is None:
            return
        parent = selected.parent()
        if parent is None:
            return
        root = self._plugin_catalogue_tree.invisibleRootItem()
        grandparent = parent.parent() or root
        parent_index = grandparent.indexOfChild(parent)
        was_expanded = selected.isExpanded()
        item = parent.takeChild(parent.indexOfChild(selected))
        grandparent.insertChild(parent_index + 1, item)
        item.setExpanded(was_expanded)
        self._plugin_catalogue_tree.setCurrentItem(item)
        self._mark_plugin_catalogue_dirty()

    def _collect_plugin_catalogue_from_ui(self) -> dict:
        """Build an ordered plugin-list configuration from the editor."""

        def collect(parent: QTreeWidgetItem) -> list[dict]:
            items = []
            for index in range(parent.childCount()):
                item = parent.child(index)
                if item.data(0, _CATALOGUE_KIND_ROLE) == _CATALOGUE_GROUP:
                    items.append(
                        {"group": item.text(0).strip(), "items": collect(item)}
                    )
                    continue
                entry = {"plugin": item.text(0).strip()}
                label = item.text(1).strip()
                if label:
                    entry["label"] = label
                items.append(entry)
            return items

        return {"items": collect(self._plugin_catalogue_tree.invisibleRootItem())}

    def _save_plugin_catalogue_from_ui(self, *, show_message: bool = True) -> None:
        """Save functional plugin groups as a user YAML override."""
        config = self._collect_plugin_catalogue_from_ui()
        path = save_plugin_catalogue_config(config)
        self._plugin_catalogue_cfg = config
        self._plugin_catalogue_dirty = False
        self.plugin_catalogue_saved = True
        if show_message:
            QMessageBox.information(
                self,
                "Plugin List Saved",
                f"Plugin list configuration saved to:\n{path}",
            )

    def _load_toolbar_rows(self) -> None:
        """Populate the toolbar table from the effective toolbar configuration."""
        for button in self._toolbar_cfg.get("buttons", []):
            if button.get("separator"):
                self._add_separator_row()
                continue
            self._add_toolbar_row(
                name=button.get("name", ""),
                sequence=button.get("sequence", ""),
                icon=button.get("image", ""),
                tooltip=button.get("tooltip", ""),
            )

    def _make_file_picker_cell(
        self,
        value: str,
        browse_callback,
        placeholder: str = "",
        enabled: bool = True,
    ) -> QWidget:
        """Create a line-edit plus browse-button cell widget."""
        cell = QWidget(self)
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(value, cell)
        if placeholder:
            edit.setPlaceholderText(placeholder)
        edit.setEnabled(enabled)
        browse = QPushButton("...", cell)
        browse.setMinimumWidth(32)
        browse.setEnabled(enabled)
        browse.clicked.connect(lambda: browse_callback(edit))
        layout.addWidget(edit)
        layout.addWidget(browse)
        return cell

    def _set_separator_row_state(self, row: int, is_separator: bool) -> None:
        """Update a row to behave as either a button row or separator row."""
        name_item = self._toolbar_table.item(row, 0)
        if name_item is None:
            name_item = QTableWidgetItem()
            self._toolbar_table.setItem(row, 0, name_item)
        if is_separator:
            name_item.setText("--- separator ---")
            name_item.setData(0x0100, _ROW_TYPE_SEPARATOR)
            for col in (1, 2, 3):
                item = self._toolbar_table.item(row, col)
                if item is not None:
                    item.setText("")
                cell_widget = self._toolbar_table.cellWidget(row, col)
                if cell_widget is not None:
                    cell_widget.setEnabled(False)
        else:
            if name_item.text() == "--- separator ---":
                name_item.setText("")
            name_item.setData(0x0100, None)
            for col in (1, 2, 3):
                cell_widget = self._toolbar_table.cellWidget(row, col)
                if cell_widget is not None:
                    cell_widget.setEnabled(True)

    def _add_toolbar_row(
        self,
        checked: bool = False,
        name: str = "",
        sequence: str = "",
        icon: str = "",
        tooltip: str = "",
    ) -> None:
        """Add one editable toolbar-button row to the table."""
        del checked
        row = self._toolbar_table.rowCount()
        self._toolbar_table.insertRow(row)
        self._toolbar_table.setItem(row, 0, QTableWidgetItem(name))
        self._toolbar_table.setItem(row, 3, QTableWidgetItem(tooltip))

        sequence_cell = self._make_file_picker_cell(
            sequence,
            self._browse_sequence_for_row,
            placeholder="sequence JSON filename",
        )
        self._toolbar_table.setCellWidget(row, 1, sequence_cell)

        icon_cell = self._make_file_picker_cell(
            icon,
            self._browse_icon_for_row,
            placeholder="icon filename",
        )
        self._toolbar_table.setCellWidget(row, 2, icon_cell)

    def _add_separator_row(self, checked: bool = False) -> None:
        """Add one toolbar separator row to the table."""
        del checked
        row = self._toolbar_table.rowCount()
        self._toolbar_table.insertRow(row)
        self._toolbar_table.setItem(row, 0, QTableWidgetItem())
        self._toolbar_table.setItem(row, 3, QTableWidgetItem(""))
        sequence_cell = self._make_file_picker_cell("", self._browse_sequence_for_row, enabled=False)
        icon_cell = self._make_file_picker_cell("", self._browse_icon_for_row, enabled=False)
        self._toolbar_table.setCellWidget(row, 1, sequence_cell)
        self._toolbar_table.setCellWidget(row, 2, icon_cell)
        self._set_separator_row_state(row, True)

    def _row_is_separator(self, row: int) -> bool:
        """Return True if the given table row represents a separator."""
        item = self._toolbar_table.item(row, 0)
        return bool(item and item.data(0x0100) == _ROW_TYPE_SEPARATOR)

    def _remove_selected_toolbar_row(self) -> None:
        """Remove the currently selected toolbar row, if any."""
        row = self._toolbar_table.currentRow()
        if row >= 0:
            self._toolbar_table.removeRow(row)

    def _browse_icon_for_row(self, line_edit: QLineEdit) -> None:
        """Choose an icon, install it in user resources, and store its basename."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Toolbar Icon",
            "",
            "Image Files (*.png *.svg *.ico *.jpg *.jpeg);;All Files (*)",
        )
        if path:
            try:
                installed = install_toolbar_icon(path)
            except OSError as exc:
                QMessageBox.critical(
                    self, "Install Toolbar Icon", f"Could not install icon:\n{exc}"
                )
                return
            line_edit.setText(installed.name)

    def _browse_sequence_for_row(self, line_edit: QLineEdit) -> None:
        """Choose a sequence, install it in user resources, and store its basename."""
        start_dir = str(user_config_root() / "sequences")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Toolbar Sequence",
            start_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            try:
                installed = install_predefined_sequence(path)
            except OSError as exc:
                QMessageBox.critical(
                    self, "Install Toolbar Sequence", f"Could not install sequence:\n{exc}"
                )
                return
            line_edit.setText(installed.name)

    def _browse_data_dir(self) -> None:
        """Open a directory chooser and populate the data-directory field."""
        current = self._data_dir_edit.text().strip()
        start = current if Path(current).is_dir() else ""
        path = QFileDialog.getExistingDirectory(self, "Select Default Data Directory", start)
        if path:
            self._data_dir_edit.setText(path)

    def _validate_toolbar_rows(self) -> list[str]:
        """Return human-readable validation warnings for the toolbar table."""
        warnings = []
        seen_sequences: set[str] = set()
        seen_names: set[str] = set()
        for row in range(self._toolbar_table.rowCount()):
            if self._row_is_separator(row):
                continue
            name_item = self._toolbar_table.item(row, 0)
            tooltip_item = self._toolbar_table.item(row, 3)
            sequence_cell = self._toolbar_table.cellWidget(row, 1)
            sequence_edit = sequence_cell.findChild(QLineEdit) if sequence_cell is not None else None
            name = name_item.text().strip() if name_item is not None else ""
            sequence = sequence_edit.text().strip() if sequence_edit is not None else ""
            if not sequence:
                warnings.append(f"Row {row + 1}: button entries should specify a sequence filename.")
                continue
            effective_name = name or Path(sequence).stem
            if effective_name in seen_names:
                warnings.append(f"Row {row + 1}: duplicate button name '{effective_name}'.")
            else:
                seen_names.add(effective_name)
            if sequence in seen_sequences:
                warnings.append(f"Row {row + 1}: duplicate sequence filename '{sequence}'.")
            else:
                seen_sequences.add(sequence)
            if tooltip_item is not None and not tooltip_item.text().strip():
                warnings.append(f"Row {row + 1}: tooltip is empty.")
        return warnings

    def _collect_toolbar_config_from_ui(self) -> dict:
        """Build a toolbar configuration mapping from the table contents."""
        buttons: list[dict] = []
        for row in range(self._toolbar_table.rowCount()):
            name_item = self._toolbar_table.item(row, 0)
            tooltip_item = self._toolbar_table.item(row, 3)
            sequence_cell = self._toolbar_table.cellWidget(row, 1)
            icon_cell = self._toolbar_table.cellWidget(row, 2)
            sequence_edit = sequence_cell.findChild(QLineEdit) if sequence_cell is not None else None
            icon_edit = icon_cell.findChild(QLineEdit) if icon_cell is not None else None

            if self._row_is_separator(row):
                buttons.append({"separator": True})
                continue

            name = name_item.text().strip() if name_item is not None else ""
            sequence = sequence_edit.text().strip() if sequence_edit is not None else ""
            tooltip = tooltip_item.text().strip() if tooltip_item is not None else ""
            image = icon_edit.text().strip() if icon_edit is not None else ""

            if not sequence:
                continue
            entry = {"name": name or Path(sequence).stem, "sequence": sequence}
            if image:
                entry["image"] = image
            if tooltip:
                entry["tooltip"] = tooltip
            buttons.append(entry)
        return {"buttons": buttons}

    def _save_toolbar_from_ui(self) -> None:
        """Save the toolbar table contents to the user toolbar.yaml file."""
        warnings = self._validate_toolbar_rows()
        if warnings:
            message = "Toolbar configuration has some issues:\n\n- " + "\n- ".join(warnings)
            result = QMessageBox.warning(
                self,
                "Toolbar Validation Warnings",
                message,
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if result != QMessageBox.StandardButton.Save:
                return
        config = self._collect_toolbar_config_from_ui()
        path = save_toolbar_config(config)
        QMessageBox.information(self, "Toolbar Saved", f"Toolbar configuration saved to:\n{path}")
        self._toolbar_cfg = config
        self.toolbar_saved = True

    def _on_accept(self) -> None:
        """Write the current field values to the user application config."""
        if self._plugin_catalogue_dirty:
            self._save_plugin_catalogue_from_ui(show_message=False)
        config = load_app_config()
        set_app_config_value(config, KEY_DEFAULT_DATA_DIR, self._data_dir_edit.text().strip())
        set_app_config_value(config, KEY_RIG, self._rig_edit.text().strip())
        set_app_config_value(config, KEY_THEME, self._theme_combo.currentText().strip().lower())
        set_app_config_value(config, KEY_FONT_SIZE, self._font_size_spin.value())
        set_app_config_value(config, KEY_EDITOR_FONT_SIZE, self._editor_font_size_spin.value())
        set_app_config_value(config, KEY_CONSOLE_FONT_SIZE, self._console_font_size_spin.value())
        for entry in FEATURE_DEFINITIONS:
            set_app_config_value(
                config,
                entry["config_key"],
                self._feature_checkboxes[entry["key"]].isChecked(),
            )
        save_app_config(config)
        self.accept()
