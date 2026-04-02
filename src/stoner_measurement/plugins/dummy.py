"""Dummy plugin — ships with the package for demonstration and testing.

The :class:`DummyPlugin` generates a simple linear ramp of data points.
It requires no hardware and is useful as a smoke-test.
"""

from __future__ import annotations

import math
from typing import Any, Generator

from PyQt6.QtWidgets import (
    QFormLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

from stoner_measurement.plugins.base_plugin import BasePlugin


class DummyPlugin(BasePlugin):
    """A built-in demo plugin that generates sine-wave data.

    Parameters accepted in ``parameters`` dict
    ------------------------------------------
    points : int
        Number of data points to generate (default 100).
    amplitude : float
        Amplitude of the sine wave (default 1.0).
    """

    @property
    def name(self) -> str:
        return "Dummy"

    def execute(
        self, parameters: dict[str, Any]
    ) -> Generator[tuple[float, float], None, None]:
        """Yield ``points`` sine-wave data points."""
        points = int(parameters.get("points", 100))
        amplitude = float(parameters.get("amplitude", 1.0))
        for i in range(points):
            x = i / max(points - 1, 1) * 2 * math.pi
            y = amplitude * math.sin(x)
            yield x, y

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a simple form for configuring the dummy plugin."""
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        self._points_spin = QSpinBox()
        self._points_spin.setRange(2, 10_000)
        self._points_spin.setValue(100)
        self._points_spin.setToolTip("Number of data points to generate")

        layout.addRow(QLabel("Points:"), self._points_spin)
        widget.setLayout(layout)
        return widget

    @property
    def configured_points(self) -> int:
        """Return the number of points configured in the UI (if the widget exists)."""
        try:
            return self._points_spin.value()
        except AttributeError:
            return 100
