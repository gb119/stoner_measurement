"""Simple reusable panel embedding one or more round dial displays.

This module provides a lightweight container suitable for dropping into other
application panels when a dial-style readback is desired.
"""

from __future__ import annotations

from qtpy.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from stoner_measurement.ui.widgets.round_dial import RoundDialWidget


class RoundDialPanel(QWidget):
    """Convenience container for one or more :class:`RoundDialWidget` instances."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QGridLayout()
        outer = QVBoxLayout(self)
        outer.addLayout(self._layout)
        outer.addStretch(1)
        self._dials: list[RoundDialWidget] = []

    def add_dial(
        self,
        title: str,
        row: int = 0,
        column: int = 0,
        *,
        minimum: float = 0.0,
        maximum: float = 360.0,
        minimum_angle: float = 0.0,
        maximum_angle: float = 360.0,
        major_tick_step: float = 30.0,
        minor_ticks_per_major: int = 4,
        label_step: float = 30.0,
        units: str = "",
    ) -> RoundDialWidget:
        """Create, configure, add, and return a dial widget."""
        dial = RoundDialWidget(self)
        dial.setTitle(title)
        dial.setRange(minimum, maximum)
        dial.setScaleAngles(minimum_angle, maximum_angle)
        dial.setTickSteps(major_tick_step, minor_ticks_per_major, label_step)
        dial.setUnitsText(units)
        self._layout.addWidget(dial, row, column)
        self._dials.append(dial)
        return dial

    def dials(self) -> list[RoundDialWidget]:
        """Return the dials currently contained in the panel."""
        return list(self._dials)
