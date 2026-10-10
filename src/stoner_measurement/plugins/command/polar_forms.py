"""Explicit angle-first polar inputs shared by Plot Trace and Plot Points."""

import numpy as np
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLineEdit, QWidget

from stoner_measurement.core.plotting.contracts import (
    ChannelMetadata,
    CoordinateBinding,
    CoordinateDescriptor,
    CoordinateSystem,
    PlotData,
    Presentation,
    SeriesUpdate,
    UpdateMode,
)
from stoner_measurement.core.plotting.service import submit_from_plugin
from stoner_measurement.ui.widgets import SISpinBox


def execute_polar_form(plugin, *, trace):
    """Evaluate independent angle and dependent radius once per execution."""
    angle = np.asarray(plugin.eval(plugin.polar_angle_expr), dtype=float)
    radius = np.asarray(plugin.eval(plugin.polar_radius_expr), dtype=float)
    dimensions = 1 if trace else 0
    if angle.ndim != dimensions or radius.ndim != dimensions or angle.shape != radius.shape:
        raise ValueError(
            "Polar inputs must be equal-length arrays for traces or scalars for points."
        )
    coordinates = CoordinateDescriptor(system=CoordinateSystem.POLAR, **plugin.polar_settings)
    metadata = {}
    errors = {}
    for channel, expression, error_expression in (
        ("angle", plugin.polar_angle_expr, plugin.polar_angle_error_expr),
        ("radius", plugin.polar_radius_expr, plugin.polar_radius_error_expr),
    ):
        if trace:
            label = plugin._channel_label_for_expression(expression)
            metadata[channel] = ChannelMetadata(label.label or channel.title(), label.unit)
        else:
            catalogue = plugin.engine_namespace.get("_values", {})
            match = next(
                ((key, value) for key, value in catalogue.items() if value == expression), None
            )
            metadata[channel] = (
                ChannelMetadata(
                    match[0].split(":", 1)[-1], getattr(match[1], "units", ""), source_key=match[0]
                )
                if match
                else ChannelMetadata(channel.title())
            )
        if error_expression:
            error = np.asarray(plugin.eval(error_expression), dtype=float)
            if error.shape != angle.shape:
                raise ValueError("Polar uncertainties must match their source inputs.")
            errors[channel] = np.atleast_1d(error)
    identity = plugin.eval(plugin.polar_id_expr)
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("Polar series ID expression must produce a nonblank string.")
    title = str(plugin.eval(plugin.polar_title_expr))
    update = SeriesUpdate(
        identity,
        PlotData(
            {"angle": np.atleast_1d(angle), "radius": np.atleast_1d(radius)}, metadata, errors
        ),
        CoordinateBinding("angle", "radius"),
        coordinates,
        mode=UpdateMode.REPLACE if trace else UpdateMode.APPEND,
        presentation=Presentation.LINE if trace else Presentation.POINTS,
        title=title,
        axes={"x": "angle", "y": "radius"},
        style=plugin.polar_style,
    )
    client = getattr(plugin.sequence_engine, "plot_client", None)
    if client is None:
        raise RuntimeError("Polar plotting requires a portable polar display.")
    if not plugin._wait_for_plot_ready(timeout=None):
        return
    submit_from_plugin(plugin, update)


class PolarFormPanel(QWidget):
    """Edit angle first, radius second, with independent saved polar conventions."""

    def __init__(self, panel):
        super().__init__(panel)
        plugin = panel.plugin
        fields = QFormLayout(self)
        fields.setAlignment(Qt.AlignmentFlag.AlignTop)

        def set_coordinate(key, text):
            if key == "angular_unit":
                previous = plugin.polar_settings.get(key, "degrees")
                value = plugin.polar_settings.get("angular_origin", 90.0)
                if previous != text:
                    value = float(np.deg2rad(value) if text == "radians" else np.rad2deg(value))
                plugin.polar_settings.update(angular_unit=text, angular_origin=value)
                origin.setValue(value)
            else:
                plugin.polar_settings.update({key: text})

        fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        fields.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for label, attribute in (
            ("Angle data (independent):", "polar_angle_expr"),
            ("Radius data (dependent):", "polar_radius_expr"),
            ("Angle uncertainty:", "polar_angle_error_expr"),
            ("Radius uncertainty:", "polar_radius_error_expr"),
        ):
            combo = panel._source_combo(
                self,
                lambda attribute=attribute: getattr(plugin, attribute),
                lambda text, attribute=attribute: setattr(plugin, attribute, text),
            )
            combo.setObjectName(attribute)
            fields.addRow(label, combo)
        for label, attribute in (
            ("Title expression:", "polar_title_expr"),
            ("Series ID expression:", "polar_id_expr"),
        ):
            edit = QLineEdit(getattr(plugin, attribute), self)
            edit.setObjectName(attribute)
            edit.textChanged.connect(
                lambda text, attribute=attribute: setattr(plugin, attribute, text)
            )
            fields.addRow(label, edit)
        for label, key, choices, default in (
            ("Angle source units:", "angular_unit", ["degrees", "radians"], "degrees"),
            ("Angle wrapping:", "wrapping", ["none", "positive", "signed"], "none"),
        ):
            combo = QComboBox(self)
            combo.setObjectName("polar_" + key)
            combo.addItems(choices)
            combo.setCurrentText(plugin.polar_settings.get(key, default))
            combo.currentTextChanged.connect(lambda text, key=key: set_coordinate(key, text))
            fields.addRow(label, combo)
        origin = SISpinBox(
            self, value=plugin.polar_settings.get("angular_origin", 90.0), siPrefix=False
        )
        origin.setObjectName("polar_angular_origin")
        origin.sigValueChanged.connect(
            lambda spin: plugin.polar_settings.update(angular_origin=float(spin.value()))
        )
        fields.addRow("Zero direction (source angle units):", origin)
        clockwise = QCheckBox("Angle increases clockwise", self)
        clockwise.setObjectName("polar_clockwise")
        clockwise.setChecked(plugin.polar_settings.get("clockwise", True))
        clockwise.toggled.connect(lambda value: plugin.polar_settings.update(clockwise=value))
        fields.addRow(clockwise)
        for label, key, choices, default in (
            (
                "Line style:",
                "line_style",
                ["solid", "dash", "dot", "dash-dot", "none"],
                "solid" if hasattr(plugin, "trace_key") else "none",
            ),
            (
                "Point style:",
                "point_style",
                ["none", "circle", "square", "triangle", "diamond", "plus", "cross"],
                "none" if hasattr(plugin, "trace_key") else "circle",
            ),
        ):
            combo = QComboBox(self)
            combo.addItems(choices)
            combo.setCurrentText(plugin.polar_style.get(key, default))
            combo.currentTextChanged.connect(
                lambda text, key=key: plugin.polar_style.update({key: text})
            )
            fields.addRow(label, combo)
        colour = QLineEdit(plugin.polar_style.get("colour", ""), self)
        colour.setPlaceholderText("Automatic, or a colour name / #RRGGBB")
        colour.textChanged.connect(
            lambda text: (
                plugin.polar_style.update(colour=text)
                if text
                else plugin.polar_style.pop("colour", None)
            )
        )
        fields.addRow("Colour:", colour)
        for label, key, default in (
            ("Line width:", "line_width", 1.5),
            ("Point size:", "point_size", 6),
        ):
            size = SISpinBox(
                self, value=plugin.polar_style.get(key, default), bounds=(0.1, 100), siPrefix=False
            )
            size.sigValueChanged.connect(
                lambda spin, key=key: plugin.polar_style.update({key: float(spin.value())})
            )
            fields.addRow(label, size)
