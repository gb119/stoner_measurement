"""Percentage slider compound widget.

Provides :class:`PercentSliderWidget`, a horizontal slider paired with a
numeric spin box that together allow setting a 0–100 % value either by
dragging the slider or by typing a precise percentage.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QSlider,
    QWidget,
)

#: Number of discrete slider steps across the full 0–100 % range.
_SLIDER_STEPS = 1000


class PercentSliderWidget(QWidget):
    """Compound widget combining a horizontal slider and a numeric spin box for 0-100 % values.

    Dragging the slider or editing the spin box updates both controls
    simultaneously.  The widget emits ``valueChanged`` whenever the value
    changes via user interaction.

    Args:
        parent (QWidget | None):
            Optional parent widget.

    Attributes:
        valueChanged (pyqtSignal):
            Emitted with the new ``float`` percentage whenever the value
            changes via user interaction.

    Examples:
        >>> from stoner_measurement.ui.widgets import PercentSliderWidget
        >>> widget = PercentSliderWidget()
        >>> widget.setValue(42.5)
        >>> widget.value()
        42.5
    """

    valueChanged = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialise the widget with default range 0–100 %."""
        super().__init__(parent)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, _SLIDER_STEPS)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(10)
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.setTickInterval(_SLIDER_STEPS // 10)

        self._spinbox = QDoubleSpinBox()
        self._spinbox.setRange(0.0, 100.0)
        self._spinbox.setDecimals(1)
        self._spinbox.setSuffix(" %")
        self._spinbox.setSingleStep(1.0)
        self._spinbox.setFixedWidth(80)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._slider)
        layout.addWidget(self._spinbox)

        self._slider.valueChanged.connect(self._on_slider_changed)
        self._spinbox.valueChanged.connect(self._on_spinbox_changed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def value(self) -> float:
        """Return the current percentage value.

        Returns:
            (float):
                Current value in the range [0.0, 100.0].

        Examples:
            >>> widget = PercentSliderWidget()
            >>> widget.value()
            0.0
        """
        return self._spinbox.value()

    def setValue(self, value: float) -> None:  # noqa: N802 - Qt naming convention
        """Set the current percentage value, updating both controls.

        Args:
            value (float):
                Desired percentage in the range [0.0, 100.0].  Values outside
                this range are clamped by the underlying spin box.

        Examples:
            >>> widget = PercentSliderWidget()
            >>> widget.setValue(75.0)
            >>> widget.value()
            75.0
        """
        self._spinbox.blockSignals(True)
        self._slider.blockSignals(True)
        try:
            self._spinbox.setValue(value)
            canonical_value = self._spinbox.value()
            self._slider.setValue(round(canonical_value / 100.0 * _SLIDER_STEPS))
        finally:
            self._spinbox.blockSignals(False)
            self._slider.blockSignals(False)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt naming convention
        """Enable or disable both the slider and the spin box.

        Args:
            enabled (bool):
                ``True`` to enable both controls; ``False`` to disable them.

        Examples:
            >>> widget = PercentSliderWidget()
            >>> widget.setEnabled(False)
            >>> widget.isEnabled()
            False
        """
        self._slider.setEnabled(enabled)
        self._spinbox.setEnabled(enabled)
        super().setEnabled(enabled)

    def setToolTip(self, tip: str) -> None:  # noqa: N802 - Qt naming convention
        """Set the tooltip on both child controls and the container widget.

        Args:
            tip (str):
                Tooltip string to display.
        """
        self._slider.setToolTip(tip)
        self._spinbox.setToolTip(tip)
        super().setToolTip(tip)

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

    def _on_slider_changed(self, slider_value: int) -> None:
        """Synchronise spin box when slider moves."""
        percent = slider_value / _SLIDER_STEPS * 100.0
        self._spinbox.blockSignals(True)
        try:
            self._spinbox.setValue(percent)
            canonical_percent = self._spinbox.value()
        finally:
            self._spinbox.blockSignals(False)
        self.valueChanged.emit(canonical_percent)

    def _on_spinbox_changed(self, percent: float) -> None:
        """Synchronise slider when spin box value changes."""
        current_percent = self._spinbox.value()
        self._slider.blockSignals(True)
        try:
            self._slider.setValue(round(current_percent / 100.0 * _SLIDER_STEPS))
        finally:
            self._slider.blockSignals(False)
        self.valueChanged.emit(current_percent)
