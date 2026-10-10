"""Shared explicit surface bindings and display-aware plot command controls."""

from copy import deepcopy
from uuid import uuid4

import numpy as np
from qtpy.QtCore import QObject, Qt  # type: ignore[attr-defined]
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.plotting.contracts import (
    AngleWrapping,
    AngularUnit,
    ChannelMetadata,
    CoordinateDescriptor,
    CoordinateSystem,
    PlotData,
    PlotOperation,
    PlotRequest,
    Presentation,
    SphericalConvention,
)
from stoner_measurement.core.plotting.producers import generalised_update
from stoner_measurement.core.plotting.regrid import regrid_trace
from stoner_measurement.core.plotting.surfaces import prepare_surface
from stoner_measurement.plugins.trace_catalog_ui import trace_channel_items
from stoner_measurement.qt_compat import pyqtSlot
from stoner_measurement.ui.widgets import SISpinBox

FORM_NAMES = {
    "xy": "XY",
    "polar": "Polar (angle, radius)",
    "xy_intensity": "XY intensity",
    "xyz": "XYZ",
    "xyz_value": "XYZ + value",
}
FORM_DEFAULTS = {
    "plot_form": "xy",
    "new_x_expr": "",
    "fixed_y_expr": "0",
    "z_expr": "",
    "value_expr": "",
    "coordinate_y_expr": "0",
    "fixed_y_label": "",
    "fixed_y_unit": "",
    "surface_id_expr": "",
    "acquisition_id_expr": "'default'",
    "slice_id_expr": "",
    "duplicate_policy": "reject",
    "reset_on_change": False,
    "coordinate_settings": {},
    "z_entries": [],
    "new_x_error_expr": "",
    "z_error_expr": "",
    "regrid_policy": "mean",
    "regrid_bounds": "nearest",
    "polar_angle_expr": "",
    "polar_radius_expr": "",
    "polar_angle_error_expr": "",
    "polar_radius_error_expr": "",
    "polar_id_expr": "",
    "polar_title_expr": "'Angular signal'",
    "polar_settings": {"angular_unit": "degrees", "angular_origin": 90.0, "clockwise": True},
    "polar_style": {},
}


def initialise_forms(plugin) -> None:
    """Give additional forms independent fields without altering XY settings."""
    restore_forms(plugin, {})


def restore_forms(plugin, data) -> None:
    """Restore optional fields with compatible XY defaults for older JSON."""
    for name, default in FORM_DEFAULTS.items():
        setattr(plugin, name, deepcopy(data.get(name, default)))
    _ensure_surface_identity(plugin)
    if not plugin.polar_id_expr.strip():
        plugin.polar_id_expr = repr(uuid4().hex)


def _ensure_surface_identity(plugin) -> None:
    """Persist one automatic identity when the surface expression is blank."""
    expression = plugin.surface_id_expr
    if isinstance(expression, str) and not expression.strip():
        plugin.surface_id_expr = repr(uuid4().hex)


def serialise_forms(plugin) -> dict:
    """Return independent JSON-compatible bindings, excluding live UI objects."""
    return {name: deepcopy(getattr(plugin, name)) for name in FORM_DEFAULTS}


def descriptor(plugin) -> CoordinateDescriptor:
    """Validate the explicitly configured source coordinate convention."""
    return CoordinateDescriptor(**plugin.coordinate_settings)


def supported_forms(plugin) -> set[str]:
    """Discover complete forms from capabilities, never renderer names."""
    client = getattr(plugin.sequence_engine, "plot_client", None)
    caps = client.capabilities() if client is not None else None
    if caps is None:
        return {"xy"}
    forms: set[str] = set()
    if PlotOperation.UPDATE_SERIES not in caps.operations:
        return forms
    if (CoordinateSystem.CARTESIAN, 2) in caps.layouts and Presentation.LINE in caps.presentations:
        forms.add("xy")
    presentation = Presentation.LINE if hasattr(plugin, "trace_key") else Presentation.POINTS
    if (CoordinateSystem.POLAR, 2) in caps.layouts and presentation in caps.presentations:
        forms.add("polar")
    try:
        coordinates = descriptor(plugin)
    except ValueError:
        return forms
    if 1 not in caps.surface_versions:
        return forms
    presentation = Presentation.SURFACE if hasattr(plugin, "trace_key") else Presentation.POINTS
    if (coordinates.system, 3) in caps.layouts and presentation in caps.presentations:
        forms.add("xyz")
        if caps.value_channel:
            forms.add("xyz_value")
    if (
        (coordinates.system, 2) in caps.layouts
        and caps.value_channel
        and Presentation.INTENSITY in caps.presentations
    ):
        forms.add("xy_intensity")
    return forms


def scalar(plugin, expression: str) -> float:
    """Evaluate one numeric scalar, rejecting arrays rather than coercing them."""
    value = np.asarray(plugin.eval(expression), dtype=float)
    if value.ndim != 0:
        raise ValueError("A fixed/point coordinate or value must be a scalar.")
    return float(value)


def _identity(plugin, expression, description) -> str:
    value = plugin.eval(expression)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{description} expression must produce a nonblank string.")
    return value


def _submit_updates(plugin, updates) -> None:
    for update in updates:
        prepare_surface(update, None)
    client = getattr(plugin.sequence_engine, "plot_client", None)
    if client is not None:
        caps = client.capabilities()
        for update in updates:
            reasons = caps.unsupported_reasons(PlotRequest(update)) if caps is not None else ()
            if reasons:
                raise RuntimeError(" ".join(reasons))
    elif getattr(plugin.sequence_engine, "plot_widget", None) is not None:
        raise RuntimeError("Additional plot forms require the portable plotting service.")
    if len({update.series_id for update in updates}) != len(updates):
        raise ValueError("Measured Z entries must have distinct surface identities.")
    if client is not None:
        from stoner_measurement.core.plotting.service import submit_many_from_plugin

        submit_many_from_plugin(plugin, updates)


def execute_trace_form(plugin) -> None:
    """Capture live arrays and fixed Y once, then submit an atomic slice."""
    if plugin.plot_form == "polar":
        from stoner_measurement.plugins.command.polar_forms import execute_polar_form

        execute_polar_form(plugin, trace=True)
        return
    xs = np.asarray(plugin.eval(plugin.new_x_expr), dtype=float)
    zs = np.asarray(plugin.eval(plugin.z_expr), dtype=float)
    if xs.ndim != 1 or zs.ndim != 1 or xs.shape != zs.shape:
        raise ValueError("Surface trace X/Z must be one-dimensional arrays of equal length.")
    y = scalar(plugin, plugin.fixed_y_expr)
    _ensure_surface_identity(plugin)
    surface_id = _identity(plugin, plugin.surface_id_expr, "Surface identity")
    slice_id = (
        _identity(plugin, plugin.slice_id_expr, "Slice identity")
        if plugin.slice_id_expr
        else repr(y)
    )
    values = plugin.eval(plugin.value_expr) if plugin.plot_form == "xyz_value" else None
    fixed_metadata = _scalar_metadata(plugin, plugin.fixed_y_expr)
    labels = {
        "x": plugin._channel_label_for_expression(plugin.new_x_expr),
        "z": plugin._channel_label_for_expression(plugin.z_expr),
        "y": ChannelMetadata(
            plugin.fixed_y_label or fixed_metadata.name, plugin.fixed_y_unit or fixed_metadata.unit
        ),
    }
    if values is not None:
        labels["value"] = plugin._channel_label_for_expression(plugin.value_expr)
    errors = {
        key: plugin.eval(expression)
        for key, expression in (("x", plugin.new_x_error_expr), ("z", plugin.z_error_expr))
        if expression
    }
    acquisition_id = _identity(plugin, plugin.acquisition_id_expr, "Acquisition identity")
    client = getattr(plugin.sequence_engine, "plot_client", None)
    grid_reader = getattr(client, "surface_x_grid", None)
    target = grid_reader(surface_id, acquisition_id) if callable(grid_reader) else None
    channels = {"x": xs, "z": zs}
    if values is not None:
        channels["value"] = values
    data = regrid_trace(
        PlotData(channels, uncertainties=errors),
        target,
        policy=plugin.regrid_policy,
        bounds=plugin.regrid_bounds,
    )
    xs, zs = data.channels["x"], data.channels["z"]
    ys = np.full(xs.shape, y)
    values = data.channels.get("value")
    errors = data.uncertainties
    update = generalised_update(
        surface_id,
        xs,
        ys,
        zs,
        form=plugin.plot_form,
        slice_id=slice_id,
        acquisition_id=acquisition_id,
        duplicates=plugin.duplicate_policy,
        reset_on_change=plugin.reset_on_change,
        coordinates=descriptor(plugin),
        labels=labels,
        errors=errors,
        values=values,
        title=str(plugin.eval(plugin.title_expr)) if plugin.title_expr else surface_id,
        style=plugin._build_style_dict(),
    )
    _submit_updates(plugin, [update])


def _scalar_metadata(plugin, expression) -> ChannelMetadata:
    for key, entry in plugin.engine_namespace.get("_values", {}).items():
        if entry == expression:
            return ChannelMetadata(
                key.split(":", 1)[-1], getattr(entry, "units", ""), source_key=key
            )
    return ChannelMetadata()


def execute_points_form(plugin, axis_label) -> None:
    """Resolve shared scalar coordinates once and append explicit measured Z cells."""
    if plugin.plot_form == "polar":
        from stoner_measurement.plugins.command.polar_forms import execute_polar_form

        execute_polar_form(plugin, trace=False)
        return
    catalog = plugin.engine_namespace.get("_values", {})

    def label_for(expression, key=""):
        key = key or next(
            (key for key, value in catalog.items() if value == expression), expression
        )
        return axis_label(key, catalog.get(key, expression))

    x = scalar(plugin, plugin.new_x_expr)
    y = scalar(plugin, plugin.coordinate_y_expr)
    value = scalar(plugin, plugin.value_expr) if plugin.plot_form == "xyz_value" else None
    acquisition = _identity(plugin, plugin.acquisition_id_expr, "Acquisition identity")
    updates = []
    for entry in plugin.z_entries:
        expression = entry.get("expr") or catalog.get(entry.get("key"), "")
        if not expression:
            raise ValueError("Each measured Z entry requires a source or expression.")
        z = scalar(plugin, expression)
        surface_id = _identity(plugin, entry.get("surface_id_expr", ""), "Surface identity")
        labels = {
            "x": label_for(plugin.new_x_expr),
            "y": label_for(plugin.coordinate_y_expr),
            "z": label_for(expression, entry.get("key", "")),
        }
        if value is not None:
            labels["value"] = label_for(plugin.value_expr)
        errors = {"z": [scalar(plugin, entry["error_expr"])]} if entry.get("error_expr") else {}
        updates.append(
            generalised_update(
                surface_id,
                [x],
                [y],
                [z],
                form=plugin.plot_form,
                append=True,
                acquisition_id=acquisition,
                duplicates=plugin.duplicate_policy,
                reset_on_change=plugin.reset_on_change,
                coordinates=descriptor(plugin),
                labels=labels,
                errors=errors,
                values=[value] if value is not None else None,
                title=entry.get("label") or surface_id,
            )
        )
    if not updates:
        raise ValueError("Configure at least one measured Z entry.")
    _submit_updates(plugin, updates)


def axis_names(engine) -> tuple[list[str], list[str]]:
    """Read the stable client's public axes, falling back to legacy descriptions."""
    client = getattr(engine, "plot_client", None)
    if client is not None:
        axes = client.axes()
    else:
        describe = getattr(getattr(engine, "plot_widget", None), "plot_axis_descriptions", None)
        axes = describe() if callable(describe) else ()
    return (
        [axis.name for axis in axes if axis.slot == "x"] or ["bottom"],
        [axis.name for axis in axes if axis.slot == "y"] or ["left"],
    )


def refresh_axis_combo(combo, names, selected) -> None:
    """Refresh choices while retaining saved assignments, including unavailable ones."""
    combo.blockSignals(True)
    combo.clear()
    combo.addItems(names)
    if selected and selected not in names:
        combo.addItem(selected)
        combo.setItemData(
            combo.count() - 1,
            "Configured axis is unavailable on the current display.",
            Qt.ItemDataRole.ToolTipRole,
        )
    combo.setCurrentText(selected)
    combo.blockSignals(False)


class PlotContextBinding(QObject):
    """Own display notifications for a configuration page, including engine reattachment."""

    def __init__(self, plugin, parent, callback):
        super().__init__(parent)
        self.plugin, self.callback = plugin, callback
        self.client = None
        self.snapshot = None
        plugin.plot_context_changed.connect(self.rebind)
        self.rebind()

    @pyqtSlot()
    def rebind(self):
        """Disconnect the previous client before following a new engine endpoint."""
        if self.client is not None:
            signal = getattr(self.client, "descriptions_changed", None)
            if signal is not None:
                signal.disconnect(self.refresh)
        self.client = getattr(self.plugin.sequence_engine, "plot_client", None)
        if self.client is not None:
            signal = getattr(self.client, "descriptions_changed", None)
            if signal is not None:
                signal.connect(self.refresh)
        self.snapshot = None
        self.refresh()

    @pyqtSlot()
    def refresh(self):
        """Ignore data-only descriptions updates; refresh on axes/capability changes."""
        snapshot = (
            axis_names(self.plugin.sequence_engine),
            self.client.capabilities() if self.client is not None else None,
        )
        if snapshot != self.snapshot:
            self.snapshot = snapshot
            self.callback()


class PlotFormPanel(QWidget):
    """Edit optional bindings and retain saved unsupported forms visibly.

    Args:
        plugin (CommandPlugin): Plot Trace or Plot Points instance.
        parent (QWidget): Owning configuration page.
        on_form_changed (callable): Refresh the existing XY controls.
    """

    def __init__(self, plugin, parent, on_form_changed):
        super().__init__(parent)
        self.plugin, self.on_form_changed = plugin, on_form_changed
        self.sources = {}
        self.source_combos = []
        self.catalog_engine = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.forms = QComboBox(self)
        self.forms.setObjectName("plot_form")
        form_layout = QFormLayout()
        form_layout.addRow("Plot form:", self.forms)
        layout.addLayout(form_layout)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.options = QWidget(self)
        self.fields = QFormLayout(self.options)
        self.fields.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.fields.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.fields.setContentsMargins(0, 0, 0, 0)
        self.options_area = QScrollArea(self)
        self.options_area.setWidgetResizable(True)
        self.options_area.setFixedHeight(290)
        self.options_area.setWidget(self.options)
        layout.addWidget(self.options_area)
        self._source_field("X data:", "new_x_expr")
        if hasattr(plugin, "trace_key"):
            self._source_field("Measured Z:", "z_expr")
            self._source_field("Fixed Y:", "fixed_y_expr")
            self._text_field("Fixed Y label:", "fixed_y_label")
            self._text_field("Fixed Y unit:", "fixed_y_unit")
            surface_id = self._text_field("Surface ID expression:", "surface_id_expr")
            surface_id.setPlaceholderText("Empty = automatic ID for this command")
            surface_id.setToolTip(
                "Leave empty for a stable automatic surface ID, or enter a Python "
                "expression producing a nonblank string. Titles do not group surfaces."
            )
            self._text_field("Slice ID (empty = Y):", "slice_id_expr")
            self._source_field("X uncertainty:", "new_x_error_expr")
            self._source_field("Z uncertainty:", "z_error_expr")
            regrid = QComboBox(self.options)
            regrid.setObjectName("regrid_policy")
            for label, policy in (
                ("Re-grid: average repeated X", "mean"),
                ("Re-grid: first sample at X", "first"),
                ("Re-grid: last sample at X", "last"),
                ("Strict: require matching, unique X", "strict"),
            ):
                regrid.addItem(label, policy)
            regrid.setCurrentIndex(regrid.findData(plugin.regrid_policy))
            regrid.currentIndexChanged.connect(
                lambda index: setattr(plugin, "regrid_policy", regrid.itemData(index))
            )
            regrid.setToolTip(
                "Sort X and interpolate later traces onto the first trace's grid. "
                "Averaging merges sweep "
                "branches; first/last selects repeated samples in acquisition order. "
                "Acquired trace data is unchanged."
            )
            self.fields.addRow("Surface X grid:", regrid)
            bounds = QComboBox(self.options)
            bounds.setObjectName("regrid_bounds")
            bounds.addItem("Nearest valid value", "nearest")
            bounds.addItem("Leave gaps", "missing")
            bounds.setCurrentIndex(bounds.findData(plugin.regrid_bounds))
            bounds.currentIndexChanged.connect(
                lambda index: setattr(plugin, "regrid_bounds", bounds.itemData(index))
            )
            bounds.setToolTip(
                "For grid coordinates outside a trace's measured X range, hold the "
                "nearest valid boundary value or leave a gap. Internal NaN gaps remain."
            )
            self.fields.addRow("Outside X range:", bounds)
        else:
            self._source_field("Y coordinate:", "coordinate_y_expr")
            self._build_z_entries()
        self.value_combo = self._source_field("Independent value:", "value_expr")
        self._text_field("Run ID expression:", "acquisition_id_expr")
        duplicates = QComboBox(self.options)
        duplicates.addItems(["reject", "replace"])
        duplicates.setCurrentText(plugin.duplicate_policy)
        duplicates.currentTextChanged.connect(
            lambda text: setattr(plugin, "duplicate_policy", text)
        )
        self.fields.addRow("Repeated cells/slices:", duplicates)
        reset = QCheckBox("Reset when acquisition identity changes", self.options)
        reset.setChecked(plugin.reset_on_change)
        reset.toggled.connect(lambda checked: setattr(plugin, "reset_on_change", checked))
        self.fields.addRow(reset)
        self._coordinate_fields()
        from stoner_measurement.plugins.command.polar_forms import PolarFormPanel

        self.polar_options = QScrollArea(self)
        self.polar_options.setObjectName("polar_options")
        self.polar_options.setWidgetResizable(True)
        self.polar_options.setMinimumHeight(290)
        self.polar_options.setWidget(PolarFormPanel(self))
        layout.addWidget(self.polar_options, 1)
        self.forms.currentIndexChanged.connect(self._select_form)
        self.binding = PlotContextBinding(plugin, self, self.refresh)
        plugin.plot_context_changed.connect(self._bind_catalog)
        self._bind_catalog()
        self.refresh()

    def _text_field(self, label, attribute):
        edit = QLineEdit(getattr(self.plugin, attribute), self.options)
        edit.setObjectName(attribute)
        edit.textChanged.connect(lambda text: setattr(self.plugin, attribute, text))
        self.fields.addRow(label, edit)
        return edit

    def _source_field(self, label, attribute):
        combo = self._source_combo(
            self.options,
            lambda: getattr(self.plugin, attribute),
            lambda text: setattr(self.plugin, attribute, text),
        )
        combo.setObjectName(attribute)
        self.fields.addRow(label, combo)
        return combo

    def _source_combo(self, parent, read, write):
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setToolTip(
            "Select a catalogue channel or type a Python expression evaluated at execution."
        )
        combo.setCurrentText(read())
        combo.currentTextChanged.connect(lambda text: write(self.sources.get(text, text)))
        self.source_combos.append((combo, read))
        return combo

    def _build_z_entries(self):
        area = QScrollArea(self.options)
        area.setWidgetResizable(True)
        area.setFixedHeight(180)
        self.z_container = QWidget(area)
        self.z_layout = QVBoxLayout(self.z_container)
        area.setWidget(self.z_container)
        self.fields.addRow(QLabel("<b>Measured Z entries:</b>", self.options))
        self.fields.addRow(area)
        for entry in self.plugin.z_entries:
            self._add_z_row(entry)
        add = QPushButton("Add measured Z", self.options)
        add.clicked.connect(self._new_z_entry)
        self.fields.addRow(add)
        self.z_layout.addStretch()

    def _new_z_entry(self):
        entry = {"expr": "", "label": "", "surface_id_expr": repr(uuid4().hex), "error_expr": ""}
        self.plugin.z_entries.append(entry)
        self._add_z_row(entry)
        self._refresh_sources()

    def _add_z_row(self, entry):
        row = QWidget(self.z_container)
        fields = QFormLayout(row)
        fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        fields.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        def read():
            return entry.get("expr") or self.plugin.engine_namespace.get("_values", {}).get(
                entry.get("key"), ""
            )

        combo = self._source_combo(row, read, lambda text: entry.update(expr=text))
        fields.addRow("Z source:", combo)
        for label, key in (
            ("Label:", "label"),
            ("Surface ID expression:", "surface_id_expr"),
            ("Z uncertainty:", "error_expr"),
        ):
            edit = QLineEdit(entry.get(key, ""), row)
            edit.textChanged.connect(lambda text, key=key: entry.update({key: text}))
            fields.addRow(label, edit)
        remove = QPushButton("Remove Z", row)

        def remove_row():
            self.plugin.z_entries.remove(entry)
            self.source_combos = [
                (widget, reader) for widget, reader in self.source_combos if widget is not combo
            ]
            row.hide()
            row.deleteLater()

        remove.clicked.connect(remove_row)
        fields.addRow(remove)
        self.z_layout.insertWidget(max(0, self.z_layout.count() - 1), row)

    def _coordinate_fields(self):
        settings = self.plugin.coordinate_settings
        for label, key, choices, default in (
            ("Coordinate system:", "system", list(CoordinateSystem), "cartesian"),
            ("Angular units:", "angular_unit", list(AngularUnit), "radians"),
            ("Azimuth wrapping:", "wrapping", list(AngleWrapping), "none"),
            ("Spherical angles:", "spherical_convention", ["", *SphericalConvention], ""),
        ):
            combo = QComboBox(self.options)
            combo.addItems(choices)
            combo.setCurrentText(settings.get(key) or default)
            combo.currentTextChanged.connect(
                lambda text, key=key: self._set_coordinate(key, text or None)
            )
            self.fields.addRow(label, combo)
        origin = SISpinBox(self.options, value=settings.get("angular_origin", 0.0), siPrefix=True)
        origin.sigValueChanged.connect(
            lambda spin: self._set_coordinate("angular_origin", float(spin.value()))
        )
        self.fields.addRow("Angular origin:", origin)
        clockwise = QCheckBox(self.options)
        clockwise.setChecked(settings.get("clockwise", False))
        clockwise.toggled.connect(lambda checked: self._set_coordinate("clockwise", checked))
        self.fields.addRow("Clockwise azimuth:", clockwise)

    def _set_coordinate(self, key, value):
        self.plugin.coordinate_settings[key] = value
        self.refresh()

    @pyqtSlot()
    def _bind_catalog(self):
        if self.catalog_engine is not None:
            for name, slot in (
                ("traces_catalog_changed", self._trace_catalog_changed),
                ("values_catalog_changed", self._value_catalog_changed),
            ):
                signal = getattr(self.catalog_engine, name, None)
                if signal is not None:
                    signal.disconnect(slot)
        self.catalog_engine = self.plugin.sequence_engine
        self.trace_catalog = dict(self.plugin.engine_namespace.get("_traces", {}))
        self.value_catalog = dict(self.plugin.engine_namespace.get("_values", {}))
        if self.catalog_engine is not None:
            for name, slot in (
                ("traces_catalog_changed", self._trace_catalog_changed),
                ("values_catalog_changed", self._value_catalog_changed),
            ):
                signal = getattr(self.catalog_engine, name, None)
                if signal is not None:
                    signal.connect(slot)
        self._refresh_sources()

    @pyqtSlot(dict)
    def _trace_catalog_changed(self, catalog):
        self.trace_catalog = dict(catalog)
        self._refresh_sources()

    @pyqtSlot(dict)
    def _value_catalog_changed(self, catalog):
        self.value_catalog = dict(catalog)
        self._refresh_sources()

    def _refresh_sources(self, *_args):
        self.sources = (
            {**trace_channel_items(self.plugin, self.trace_catalog), **self.value_catalog}
            if hasattr(self.plugin, "trace_key")
            else self.value_catalog
        )
        for combo, read in self.source_combos:
            expression = read()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            combo.addItems(self.sources)
            combo.setCurrentText(
                next(
                    (label for label, expr in self.sources.items() if expr == expression),
                    expression,
                )
            )
            combo.blockSignals(False)

    def _select_form(self, _index):
        self.plugin.plot_form = self.forms.currentData()
        self.refresh()
        self.on_form_changed()

    def refresh(self):
        """Update available forms without clearing a saved unsupported binding."""
        selected = self.plugin.plot_form
        supported = supported_forms(self.plugin)
        self.forms.blockSignals(True)
        self.forms.clear()
        for form, label in FORM_NAMES.items():
            if form in supported or form == selected:
                self.forms.addItem(label if form in supported else f"{label} (unsupported)", form)
        if selected not in FORM_NAMES:
            self.forms.addItem(f"{selected} (unsupported)", selected)
        self.forms.setCurrentIndex(self.forms.findData(selected))
        self.forms.blockSignals(False)
        self.options_area.setVisible(selected not in ("xy", "polar"))
        self.polar_options.setVisible(selected == "polar")
        for widget in (self, self.parentWidget()):
            policy = widget.sizePolicy()
            policy.setVerticalPolicy(
                QSizePolicy.Policy.Expanding
                if selected == "polar"
                else QSizePolicy.Policy.Preferred
            )
            policy.setVerticalStretch(1 if selected == "polar" else 0)
            widget.setSizePolicy(policy)
        self.value_combo.setEnabled(selected == "xyz_value")
        self.status.setText(
            ""
            if selected in supported
            else "The current display does not support this saved form. Bindings are retained."
        )
        self.status.setVisible(selected not in supported)
