"""Formatting controls shared by interactive and sequence trace plots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from qtpy.QtCore import Qt
from qtpy.QtGui import QColor
from qtpy.QtWidgets import QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QMenu, QPushButton

from stoner_measurement.ui.theme import button_swatch_stylesheet, contrasting_text_colour

_LINE_STYLES = ("", "solid", "dash", "dot", "dash-dot", "none")
_POINT_STYLES = ("", "none", "circle", "square", "triangle", "diamond", "plus", "cross")


class _StyleSettings(Protocol):
    colour: str
    line_style: str
    point_style: str
    line_width: float
    point_size: float


@dataclass
class TracePlotStyle:
    """Optional appearance overrides for a trace plot."""

    colour: str = ""
    line_style: str = ""
    point_style: str = ""
    line_width: float = 0.0
    point_size: float = 0.0


def trace_style_dict(settings: _StyleSettings) -> dict[str, str | float]:
    """Return only explicitly configured style overrides."""
    style = {
        "colour": settings.colour,
        "line_style": settings.line_style,
        "point_style": settings.point_style,
        "line_width": max(0.0, settings.line_width),
        "point_size": max(0.0, settings.point_size),
    }
    return {key: value for key, value in style.items() if value}


def choose_trace_colour(current_colour, title, parent=None) -> str:
    """Pick a colour, retaining the previous value when cancelled."""
    current = QColor(current_colour)
    selected = QColorDialog.getColor(
        current if current.isValid() else QColor("black"),
        parent,
        title,
        QColorDialog.ColorDialogOption.DontUseNativeDialog,
    )
    return selected.name(QColor.NameFormat.HexRgb) if selected.isValid() else current_colour


def add_trace_style_controls(
    layout: QFormLayout, settings: _StyleSettings, *, choose_colour=None
) -> None:
    """Add the shared colour, style and size controls to a plot form."""
    parent = layout.parentWidget()
    button = QPushButton(parent)
    button.setToolTip("Click to choose a colour. Right-click to restore the automatic colour.")

    def update_swatch() -> None:
        colour = QColor(settings.colour)
        label = colour.name(QColor.NameFormat.HexRgb) if colour.isValid() else settings.colour
        button.setText(label or "(auto)")
        button.setStyleSheet(
            button_swatch_stylesheet(label, contrasting_text_colour(label))
            if colour.isValid()
            else ""
        )

    def pick_colour() -> None:
        title = "Select trace colour"
        settings.colour = (
            choose_colour(settings.colour, title)
            if choose_colour is not None
            else choose_trace_colour(settings.colour, title, parent)
        )
        update_swatch()

    def reset_colour(pos) -> None:
        menu = QMenu(button)
        reset = menu.addAction("Auto (clear colour)")
        if menu.exec(button.mapToGlobal(pos)) == reset:
            settings.colour = ""
            update_swatch()

    update_swatch()
    button.clicked.connect(pick_colour)
    button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    button.customContextMenuRequested.connect(reset_colour)
    layout.addRow("Colour:", button)

    for label, attr, options in (
        ("Line style:", "line_style", _LINE_STYLES),
        ("Point style:", "point_style", _POINT_STYLES),
    ):
        combo = QComboBox(parent)
        for option in options:
            combo.addItem(option or "(default)", option)
        current = combo.findData(getattr(settings, attr))
        combo.setCurrentIndex(max(0, current))
        setattr(settings, attr, combo.currentData())
        combo.currentTextChanged.connect(
            lambda _text, field=attr, control=combo: setattr(settings, field, control.currentData())
        )
        layout.addRow(label, combo)

    for label, attr in (("Line width:", "line_width"), ("Point size:", "point_size")):
        spin = QDoubleSpinBox(parent)
        spin.setRange(0.0, 100.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setSpecialValueText("default")
        spin.setValue(getattr(settings, attr))
        spin.valueChanged.connect(lambda value, field=attr: setattr(settings, field, value))
        layout.addRow(label, spin)
