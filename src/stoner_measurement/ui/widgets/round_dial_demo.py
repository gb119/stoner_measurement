"""Demonstration widgets for :class:`stoner_measurement.ui.widgets.RoundDialWidget`."""

from __future__ import annotations

from qtpy.QtCore import QTimer, Qt
from qtpy.QtWidgets import (
    QComboBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from stoner_measurement.ui.widgets.round_dial import RoundDialWidget


class RoundDialDemoWidget(QWidget):
    """Small reusable demo panel showcasing common dial configurations."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(
            [
                "Motor position",
                "Compass",
                "Bidirectional angle",
                "Percent",
                "Clock",
            ]
        )

        self._dial = RoundDialWidget()
        self._dial.setTitle("Motor Position")
        self._dial.setAngleValueMode()
        self._dial.setValue(0.0)

        self._value_label = QLabel()
        self._value_label.setAlignment(Qt.AlignCenter)

        self._preset_label = QLabel("Preset:")
        self._preset_label.setBuddy(self._mode_combo)

        top = QVBoxLayout(self)
        top.setContentsMargins(12, 12, 12, 12)
        top.setSpacing(8)

        top.addWidget(self._preset_label, 0, Qt.AlignLeft)
        top.addWidget(self._mode_combo, 0)

        top.addWidget(self._dial, 1)
        self._dial.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._dial.setMinimumHeight(260)
        top.addWidget(self._value_label)
        self._mode_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._preset_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._value_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        top.setStretchFactor(self._dial, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._advance_demo_value)

        self._mode_combo.currentTextChanged.connect(self._apply_preset)
        self._dial.valueChanged.connect(self._update_value_label)

        self._apply_preset(self._mode_combo.currentText())
        self._timer.start()

    @property
    def dial(self) -> RoundDialWidget:
        """Return the live dial widget used by the demo."""
        return self._dial

    def _apply_preset(self, preset: str) -> None:
        preset = preset.strip().lower()
        self._dial.setScaleBandVisible(False)
        self._dial.setScaleBandStops([])
        self._dial.setLabelRadiusFactor(0.72)

        if preset == "motor position":
            self._dial.setTitle("Motor Position")
            self._dial.setAngleValueMode()
            self._dial.setTopReservedFraction(0.18)
            self._dial.setBottomReservedFraction(0.18)
            self._dial.setTitleVerticalOffsetFraction(0.015)
            self._dial.setLabelBackgroundVisible(False)
            self._dial.setRange(0.0, 360.0)
            self._dial.setScaleAngles(0.0, 360.0)
            self._dial.setTickSteps(30.0, 4, 30.0)
            self._dial.setPreferredLabelCounts([12, 8, 6, 4])
            self._dial.setValue(0.0)
        elif preset == "compass":
            self._dial.setCompassMode()
            self._dial.setCompassLabelMode(8)
            self._dial.setTopReservedFraction(0.18)
            self._dial.setBottomReservedFraction(0.18)
            self._dial.setTitleVerticalOffsetFraction(0.015)
            self._dial.setLabelBackgroundVisible(False)
            self._dial.setValue(0.0)
        elif preset == "bidirectional angle":
            self._dial.setTitle("Angle")
            self._dial.setBidirectionalAngleMode()
            self._dial.setTopReservedFraction(0.18)
            self._dial.setBottomReservedFraction(0.18)
            self._dial.setTitleVerticalOffsetFraction(0.015)
            self._dial.setLabelBackgroundVisible(False)
            self._dial.setValue(0.0)
        elif preset == "clock":
            self._dial.setTitle("Clock")
            self._dial.setClockMode()
            self._dial.setTopReservedFraction(0.18)
            self._dial.setBottomReservedFraction(0.18)
            self._dial.setTitleVerticalOffsetFraction(0.015)
            self._dial.setLabelBackgroundVisible(False)
            self._dial.setPreferredLabelCounts(None)
            self._dial.setValue(0.0)
        else:
            self._dial.setTitle("Position")
            self._dial.clearCustomLabels()
            self._dial.setRange(0.0, 100.0)
            self._dial.setScaleAngles(-225.0, 45.0)
            self._dial.setTopReservedFraction(0.16)
            self._dial.setBottomReservedFraction(0.18)
            self._dial.setTickSteps(10.0, 4, 10.0)
            self._dial.setPreferredLabelCounts([11, 6])
            self._dial.setDecimals(0)
            self._dial.setWrap(False)
            self._dial.setUnitsText("%")
            self._dial.setValue(0.0)
            self._dial.setScaleBandVisible(True)
            self._dial.setScaleBandStops([(0.0, "#b22222"), (50.0, "#d9a400"), (100.0, "#228b22")])
            self._dial.setLabelBackgroundVisible(False)
            self._dial.setLabelRadiusFactor(0.76)
        self._update_value_label(self._dial.value())

    def _advance_demo_value(self) -> None:
        preset = self._mode_combo.currentText().strip().lower()
        if preset in {"motor position", "compass"}:
            next_value = self._dial.value() + 2.0
        elif preset == "clock":
            next_value = self._dial.value() + (1.0 / 12.0)
        elif preset == "bidirectional angle":
            next_value = self._dial.value() + 4.0
            if next_value > self._dial.maximumValue():
                next_value = self._dial.minimumValue()
        else:
            next_value = self._dial.value() + 1.5
            if next_value > self._dial.maximumValue():
                next_value = self._dial.minimumValue()
        self._dial.setValue(next_value)

    def _update_value_label(self, value: float) -> None:
        if self._mode_combo.currentText().strip().lower() == "clock":
            self._value_label.setText(f"Current value: {self._dial.formattedValueText()}")
            return
        suffix = self._dial.unitsText() or self._dial.valueTextSuffix()
        decimals = self._dial.decimals()
        self._value_label.setText(f"Current value: {value:.{decimals}f}{suffix}")
